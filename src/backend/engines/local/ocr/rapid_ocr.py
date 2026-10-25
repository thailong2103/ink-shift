"""RapidOCR (PP-OCRv4 ONNX) adapter for multilingual, Latin, and Chinese manga recognition."""

from __future__ import annotations

import importlib
import io
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from src.backend.engines.local.ocr.text_assembler import assemble_comic_lines
from src.backend.logging import get_logger

if TYPE_CHECKING:
    from src.backend.detection.assembler import BubbleWorkItem

logger = get_logger("ocr.rapid")


class RapidOCRAdapter:
    """Multilingual OCR adapter wrapping rapidocr-onnxruntime with DirectML GPU acceleration."""

    def __init__(self, rapidocr_engine: Any | None = None) -> None:
        self._engine = rapidocr_engine

    @property
    def name(self) -> str:
        """OCR adapter identifier."""
        return "rapidocr"

    @property
    def supports_full_page(self) -> bool:
        """RapidOCR supports single-pass full-page text detection and recognition."""
        return True

    async def is_available(self) -> bool:
        """Check whether RapidOCR runtime is importable or engine is loaded."""
        if self._engine is not None:
            return True
        try:
            importlib.import_module("rapidocr_onnxruntime")
            return True
        except ImportError:
            return False

    def _ensure_engine(self) -> None:
        """Lazily initialize RapidOCR engine with DirectML GPU acceleration and CPU fallback."""
        if self._engine is not None:
            return

        logger.debug("Initializing RapidOCR engine (PP-OCRv4 ONNX)...")
        try:
            rapid_module = importlib.import_module("rapidocr_onnxruntime")
            rapid_cls = rapid_module.RapidOCR
            try:
                # Attempt DirectML acceleration on DirectX 12 hardware (disable cls for speed)
                self._engine = rapid_cls(
                    det_use_dml=True,
                    cls_use_dml=True,
                    rec_use_dml=True,
                    use_cls=False,
                )
                logger.debug("RapidOCR initialized successfully with DirectML GPU acceleration (use_cls=False).")
            except (RuntimeError, ValueError, OSError, AttributeError) as dml_exc:
                logger.warning(
                    "RapidOCR DirectML initialization failed (%s); falling back to CPU.",
                    dml_exc,
                )
                self._engine = rapid_cls(use_cls=False)
                logger.debug("RapidOCR initialized successfully with CPU execution provider (use_cls=False).")
        except (ImportError, AttributeError) as exc:
            logger.exception("Failed to initialize RapidOCR engine")
            raise RuntimeError(
                f"Failed to initialize RapidOCR engine: {exc}. "
                "Ensure 'rapidocr-onnxruntime' is installed in the environment."
            ) from exc

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        """Extract text from a list of cropped speech bubble images."""
        if not image_crops:
            return []

        self._ensure_engine()
        engine = self._engine
        if engine is None:
            raise RuntimeError("RapidOCR engine failed to initialize.")

        t0 = time.perf_counter()
        results: list[str] = []
        for i, crop_bytes in enumerate(image_crops):
            if not crop_bytes:
                results.append("")
                continue

            try:
                img = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
                img_np = np.array(img)
            except (OSError, ValueError) as img_err:
                logger.debug("Crop [%d/%d] invalid image bytes: %s", i + 1, len(image_crops), img_err)
                results.append("")
                continue

            # Run inference via RapidOCR
            ocr_output = engine(img_np)
            if not ocr_output or not isinstance(ocr_output, (list, tuple)):
                results.append("")
                continue

            # RapidOCR returns (result, elapse_time)
            ocr_result = ocr_output[0]
            if not ocr_result or not isinstance(ocr_result, list):
                results.append("")
                continue

            # Sort detected text lines vertically (top-to-bottom)
            # Each entry in ocr_result is typically: [box_points, text, confidence]
            try:
                sorted_lines = sorted(
                    ocr_result,
                    key=lambda item: float(item[0][0][1]) if len(item) > 0 and len(item[0]) > 0 else 0.0,
                )
            except (IndexError, TypeError, ValueError):
                sorted_lines = ocr_result

            raw_lines: list[str] = []
            for item in sorted_lines:
                if len(item) >= 2 and item[1]:
                    raw_lines.append(str(item[1]))

            assembled = assemble_comic_lines(raw_lines)
            logger.debug(
                "RapidOCR crop [%d/%d] (%dx%d px): detected %d lines -> '%s'",
                i + 1,
                len(image_crops),
                img.width,
                img.height,
                len(raw_lines),
                assembled[:40],
            )
            results.append(assembled)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "RapidOCR batch completed: %d crops processed in %.2fms (transcribed %d/%d non-empty)",
            len(image_crops),
            elapsed_ms,
            sum(1 for r in results if r.strip()),
            len(image_crops),
        )
        return results

    async def recognize_full_page(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
    ) -> list[str]:
        """Recognize text lines across uncropped page and map into work items via spatial intersection.

        Bypasses per-bubble cropping, eliminating redundant text detection passes and orientation checks.

        Args:
            image_np: RGB numpy array or PIL Image of the uncropped page.
            work_items: Ordered sequence of BubbleWorkItem instances with canonical [0, 1000] crop_box.
            image_width: Original image width in pixels.
            image_height: Original image height in pixels.

        Returns:
            List of transcribed text strings matching the exact order and length of work_items.
        """
        if not work_items:
            return []

        if isinstance(image_np, Image.Image):
            img_array = np.array(image_np.convert("RGB"))
        else:
            img_array = image_np

        self._ensure_engine()
        engine = self._engine
        if engine is None:
            raise RuntimeError("RapidOCR engine failed to initialize.")

        t0 = time.perf_counter()
        ocr_output = engine(img_array)
        ocr_result = ocr_output[0] if (ocr_output and ocr_output[0] is not None) else []
        if not isinstance(ocr_result, list):
            ocr_result = []

        # Map each work item index to its contained text line candidates
        assigned_lines: dict[int, list[dict[str, Any]]] = {idx: [] for idx in range(len(work_items))}

        # Canonical [0, 1000] bounding boxes for spatial containment check
        boxes_canonical = [item.crop_box for item in work_items]

        # Margin in canonical [0, 1000] space to absorb slight boundary clip
        margin = 6

        for item in ocr_result:
            if not item or len(item) < 2:
                continue
            box_pts = item[0]
            text = str(item[1]).strip()
            conf = float(item[2]) if len(item) > 2 else 1.0
            if not text:
                continue

            # Centroid in physical pixels
            pts_count = len(box_pts)
            if pts_count == 0:
                continue
            cx_px = sum(float(pt[0]) for pt in box_pts) / float(pts_count)
            cy_px = sum(float(pt[1]) for pt in box_pts) / float(pts_count)

            # Normalized centroid in canonical [0, 1000] space
            norm_cx = (cx_px / max(1, image_width)) * 1000.0
            norm_cy = (cy_px / max(1, image_height)) * 1000.0

            best_idx = -1
            best_area = float("inf")

            for idx, (b_ymin, b_xmin, b_ymax, b_xmax) in enumerate(boxes_canonical):
                if (
                    (b_ymin - margin) <= norm_cy <= (b_ymax + margin)
                    and (b_xmin - margin) <= norm_cx <= (b_xmax + margin)
                ):
                    area = (b_ymax - b_ymin) * (b_xmax - b_xmin)
                    if area < best_area:
                        best_area = area
                        best_idx = idx

            if best_idx >= 0:
                assigned_lines[best_idx].append({
                    "cy": cy_px,
                    "cx": cx_px,
                    "text": text,
                    "conf": conf,
                })

        # Assemble lines per bubble in vertical reading order (top-to-bottom)
        results: list[str] = []
        for idx in range(len(work_items)):
            lines_for_bubble = assigned_lines[idx]
            if not lines_for_bubble:
                results.append("")
                continue

            sorted_lines = sorted(lines_for_bubble, key=lambda l: l["cy"])
            raw_text_lines = [l["text"] for l in sorted_lines]
            assembled = assemble_comic_lines(raw_text_lines)
            results.append(assembled)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        non_empty_count = sum(1 for r in results if r.strip())
        logger.debug(
            "RapidOCR full-page completed: %d text elements mapped to %d bubbles in %.2fms (%d non-empty)",
            len(ocr_result),
            len(work_items),
            elapsed_ms,
            non_empty_count,
        )
        return results

