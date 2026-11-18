"""RapidOCR (PP-OCRv4 ONNX) adapter for multilingual, Latin, and Chinese manga recognition."""

from __future__ import annotations

import importlib
import io
import os
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from src.backend.engines.local.ocr.text_assembler import (
    ParagraphCluster,
    assemble_comic_lines,
    clean_japanese_text,
    cluster_lines_to_paragraphs,
)
from src.backend.logging import get_logger

if TYPE_CHECKING:
    from src.backend.detection.assembler import BubbleWorkItem

logger = get_logger("ocr.rapid")


class RapidOCRAdapter:
    """Multilingual OCR adapter wrapping rapidocr-onnxruntime with DirectML GPU acceleration."""

    def __init__(self, rapidocr_engine: Any | None = None) -> None:
        self._engines: dict[str, Any] = {}
        self._custom_engine_provided = rapidocr_engine is not None
        if rapidocr_engine is not None:
            self._engines["default"] = rapidocr_engine

    @property
    def name(self) -> str:
        """OCR adapter identifier."""
        return "rapidocr"

    @property
    def _engine(self) -> Any | None:
        """Backwards-compatibility accessor for the default engine instance."""
        return self._engines.get("default")

    @property
    def supports_full_page(self) -> bool:
        """RapidOCR supports single-pass full-page text detection and recognition."""
        return True

    async def is_available(self) -> bool:
        """Check whether RapidOCR runtime is importable or an engine is already loaded."""
        if self._engines:
            return True
        try:
            importlib.import_module("rapidocr_onnxruntime")
            return True
        except ImportError:
            return False

    def _normalize_lang(self, lang: str | None) -> str:
        """Normalize language identifier to internal key."""
        if not lang or lang == "auto":
            return "default"
        code = lang.lower().strip()
        if code in ("ja", "japanese"):
            return "ja"
        if code in ("ko", "korean"):
            return "ko"
        return "default"

    def _ensure_engine(self, lang: str = "default") -> None:
        """Ensure that the engine for the requested language is initialized in the pool."""
        self._get_engine(lang)

    def _get_engine(self, lang: str = "default") -> Any:
        """Lazily initialize and cache RapidOCR engine for the target language."""
        target_lang = self._normalize_lang(lang)
        if target_lang in self._engines and self._engines[target_lang] is not None:
            return self._engines[target_lang]

        # If a single custom mock or engine was explicitly passed in constructor, reuse it
        if (
            self._custom_engine_provided
            and "default" in self._engines
            and self._engines["default"] is not None
            and not isinstance(self._engines["default"], dict)
            and target_lang != "default"
            and target_lang not in self._engines
        ):
            self._engines[target_lang] = self._engines["default"]
            return self._engines["default"]

        try:
            rapid_module = importlib.import_module("rapidocr_onnxruntime")
            rapid_cls = rapid_module.RapidOCR
        except (ImportError, AttributeError) as exc:
            logger.exception("Failed to initialize RapidOCR engine")
            raise RuntimeError(
                f"Failed to initialize RapidOCR engine: {exc}. "
                "Ensure 'rapidocr-onnxruntime' is installed in the environment."
            ) from exc

        from src.backend.config import Settings
        from src.backend.detection.downloader import ensure_ocr_model_files

        settings = Settings()
        extra_kwargs: dict[str, Any] = {}

        if target_lang in ("ja", "ko"):
            model_path_setting = (
                settings.inkshift_local_ocr_ja_model_path
                if target_lang == "ja"
                else settings.inkshift_local_ocr_ko_model_path
            )
            dict_path_setting = (
                settings.inkshift_local_ocr_ja_dict_path
                if target_lang == "ja"
                else settings.inkshift_local_ocr_ko_dict_path
            )

            resolved_model = ensure_ocr_model_files(
                target_lang,
                dest_path=model_path_setting,
                auto_download=settings.inkshift_auto_download_models,
            )
            if resolved_model is not None and resolved_model.exists():
                extra_kwargs["rec_model_path"] = str(resolved_model)
                if dict_path_setting and os.path.exists(dict_path_setting):
                    extra_kwargs["rec_keys_path"] = str(dict_path_setting)
                logger.info(
                    "Initialized specialized RapidOCR engine for '%s' using model: %s",
                    target_lang,
                    resolved_model.name,
                )
            else:
                logger.warning(
                    "Specialized OCR model for '%s' not found or failed to download; falling back to default model.",
                    target_lang,
                )
                default_engine = self._get_engine("default")
                self._engines[target_lang] = default_engine
                return default_engine

        logger.debug("Initializing RapidOCR engine (lang=%s)...", target_lang)
        try:
            # Attempt DirectML acceleration on DirectX 12 hardware (disable cls for speed)
            engine = rapid_cls(
                det_use_dml=True,
                cls_use_dml=True,
                rec_use_dml=True,
                use_cls=False,
                **extra_kwargs,
            )
            logger.debug("RapidOCR (%s) initialized successfully with DirectML GPU acceleration.", target_lang)
        except (RuntimeError, ValueError, OSError, AttributeError) as dml_exc:
            logger.warning(
                "RapidOCR DirectML (%s) initialization failed (%s); falling back to CPU.",
                target_lang,
                dml_exc,
            )
            engine = rapid_cls(use_cls=False, **extra_kwargs)
            logger.debug("RapidOCR (%s) initialized successfully with CPU execution provider.", target_lang)

        self._engines[target_lang] = engine
        return engine

    async def recognize_batch(self, image_crops: list[bytes], lang: str = "zh") -> list[str]:
        """Extract text from a list of cropped speech bubble images."""
        if not image_crops:
            return []

        engine = self._get_engine(lang)
        if engine is None:
            raise RuntimeError(f"RapidOCR engine failed to initialize for language '{lang}'.")

        is_ja = self._normalize_lang(lang) == "ja"
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
            if is_ja:
                assembled = clean_japanese_text(assembled)

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
        lang: str = "zh",
    ) -> list[str]:
        """Recognize text lines across uncropped page and map into work items via spatial intersection.

        Bypasses per-bubble cropping, eliminating redundant text detection passes and orientation checks.

        Args:
            image_np: RGB numpy array or PIL Image of the uncropped page.
            work_items: Ordered sequence of BubbleWorkItem instances with canonical [0, 1000] crop_box.
            image_width: Original image width in pixels.
            image_height: Original image height in pixels.
            lang: Language identifier ('ja', 'ko', 'zh', 'en', etc.).

        Returns:
            List of transcribed text strings matching the exact order and length of work_items.
        """
        if not work_items:
            return []

        if isinstance(image_np, Image.Image):
            img_array = np.array(image_np.convert("RGB"))
        else:
            img_array = image_np

        engine = self._get_engine(lang)
        if engine is None:
            raise RuntimeError(f"RapidOCR engine failed to initialize for language '{lang}'.")

        is_ja = self._normalize_lang(lang) == "ja"
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
            if is_ja:
                assembled = clean_japanese_text(assembled)
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

    async def recognize_direct_paragraphs(
        self,
        image_np: np.ndarray | Image.Image,
        image_width: int,
        image_height: int,
        lang: str = "zh",
    ) -> list[ParagraphCluster]:
        """Detect and recognize full-page text directly into clustered paragraphs without speech bubbles.

        Args:
            image_np: Source image as RGB numpy array or PIL Image.
            image_width: Original image width in physical pixels.
            image_height: Original image height in physical pixels.
            lang: Target OCR language identifier ('ja', 'ko', 'zh', 'en').

        Returns:
            List of ParagraphCluster objects sorted in Top-to-Bottom, Left-to-Right reading order.
        """
        if isinstance(image_np, Image.Image):
            img_array = np.array(image_np.convert("RGB"))
        else:
            img_array = image_np

        engine = self._get_engine(lang)
        if engine is None:
            raise RuntimeError(f"RapidOCR engine failed to initialize for language '{lang}'.")

        is_ja = self._normalize_lang(lang) == "ja"
        t0 = time.perf_counter()
        ocr_output = engine(img_array)
        ocr_result = ocr_output[0] if (ocr_output and ocr_output[0] is not None) else []
        if not isinstance(ocr_result, list):
            ocr_result = []

        paragraphs = cluster_lines_to_paragraphs(
            raw_ocr_lines=ocr_result,
            image_width=image_width,
            image_height=image_height,
            is_ja=is_ja,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "RapidOCR direct paragraphs completed: %d lines clustered into %d paragraphs in %.2fms (lang=%s)",
            len(ocr_result),
            len(paragraphs),
            elapsed_ms,
            lang,
        )
        return paragraphs

