"""YOLO11s-seg ONNX instance segmentation detector with DirectML acceleration."""

from __future__ import annotations

import gc
import io
import os
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

from src.backend.config import Settings
from src.backend.detection.base import (
    DetectedBubble,
    DetectedPanel,
    DetectedText,
    PageLayoutDetections,
)
from src.backend.detection.postprocess import (
    assign_child_texts_to_bubbles,
    assign_child_texts_with_orphans,
    compute_letterbox_params,
    extract_rdp_polygon,
    invert_letterbox_coords,
    normalize_box_to_1000,
)
from src.backend.detection.sorter import MangaReadingOrderSorter
from src.backend.logging import format_logfmt, get_logger

logger = get_logger("detector")


class YOLO11Detector:
    """Speech bubble and layout detector utilizing YOLO11s-seg ONNX with DirectML."""

    def __init__(
        self,
        model_path: str | None = None,
        execution_provider: str | None = None,
        onnx_session: Any | None = None,
        input_size: int = 1024,
        confidence_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        return_polygon: bool = True,
        bubble_threshold: float | None = None,
        text_threshold: float | None = None,
        panel_threshold: float | None = None,
        sfx_threshold: float | None = None,
        auto_download: bool | None = None,
        cpu_threads: int | None = None,
    ) -> None:
        settings = Settings()
        default_path = (
            settings.inkshift_local_detector_model_path
            or os.path.join(settings.inkshift_local_model_dir, "yolo11s-seg.onnx")
        )
        self._is_custom_path = model_path is not None and model_path != default_path
        self._model_path = model_path if model_path is not None else default_path
        self._provider = (
            execution_provider
            if execution_provider is not None
            else settings.inkshift_local_execution_provider
        )
        self._cpu_threads = max(
            1, cpu_threads if cpu_threads is not None else settings.inkshift_local_cpu_threads
        )
        self._session = onnx_session
        self._injected_session = onnx_session is not None
        self._last_used_monotonic: float | None = None
        self._auto_download = (
            auto_download
            if auto_download is not None
            else (settings.inkshift_auto_download_models and not self._is_custom_path)
        )
        self._input_size = input_size
        self._confidence_threshold = confidence_threshold
        self._bubble_threshold = (
            bubble_threshold
            if bubble_threshold is not None
            else (0.30 if confidence_threshold == 0.35 else confidence_threshold)
        )
        self._text_threshold = (
            text_threshold
            if text_threshold is not None
            else (0.30 if confidence_threshold == 0.35 else confidence_threshold)
        )
        self._panel_threshold = (
            panel_threshold
            if panel_threshold is not None
            else confidence_threshold
        )
        self._sfx_threshold = (
            sfx_threshold
            if sfx_threshold is not None
            else confidence_threshold
        )
        self._iou_threshold = iou_threshold
        self._return_polygon = return_polygon

    @property
    def name(self) -> str:
        """Detector identifier."""
        return "yolo11s-seg"

    @property
    def is_loaded(self) -> bool:
        """Return True when a managed (non-injected) ONNX session is loaded in memory."""
        return self._session is not None and not self._injected_session

    @property
    def last_used_monotonic(self) -> float | None:
        """Return monotonic timestamp of the latest session initialization or inference."""
        return self._last_used_monotonic

    def mark_used(self) -> None:
        """Update last-used monotonic timestamp for idle auto-unload tracking."""
        self._last_used_monotonic = time.monotonic()

    def unload_session(self) -> bool:
        """Release managed ONNX session from memory and trigger garbage collection."""
        if self._injected_session or self._session is None:
            return False
        self._session = None
        self._last_used_monotonic = None
        gc.collect()
        logger.info(format_logfmt("YoloSessionUnloaded", model_path=self._model_path))
        return True

    async def is_available(self) -> bool:
        """Check whether session is ready or model weights exist on disk."""
        if self._session is not None:
            return True
        return os.path.exists(self._model_path)

    @staticmethod
    def _build_session_options(
        ort_mod: Any, *, enable_mem_pattern: bool, intra_op_threads: int | None = None
    ) -> Any:
        """Build sequential ONNX Runtime SessionOptions preserving DirectML arena reuse."""
        opts = ort_mod.SessionOptions()
        opts.execution_mode = ort_mod.ExecutionMode.ORT_SEQUENTIAL
        opts.enable_mem_pattern = enable_mem_pattern
        if intra_op_threads is not None:
            opts.intra_op_num_threads = max(1, intra_op_threads)
        return opts

    def _ensure_session(self) -> None:
        """Lazily initialize ONNX inference session if not already loaded."""
        if self._session is not None:
            return

        if not os.path.exists(self._model_path):
            if self._auto_download:
                logger.info(
                    "Model weights not found at '%s'. Automatically downloading YOLO11s-seg ONNX from Hugging Face...",
                    self._model_path,
                )
                from src.backend.detection.downloader import ensure_model_file

                ensure_model_file(self._model_path)
            else:
                logger.error("Model weights not found at '%s'", self._model_path)
                raise FileNotFoundError(
                    f"YOLO11s-seg model weights not found at '{self._model_path}'. "
                    "Auto-download is disabled. Please run 'python scripts/download_models.py' to download required weights."
                )

        logger.debug(
            format_logfmt(
                "YoloSessionInit",
                provider=self._provider,
                weights_path=self._model_path,
            )
        )
        import importlib

        ort = importlib.import_module("onnxruntime")
        normalized_provider = self._provider.lower().strip()
        use_directml = normalized_provider in ("directml", "hybrid")

        if use_directml:
            dml_opts = self._build_session_options(ort, enable_mem_pattern=False)
            dml_providers: list[Any] = [
                ("DmlExecutionProvider", {"device_id": 0}),
                "CPUExecutionProvider",
            ]
            try:
                self._session = ort.InferenceSession(
                    self._model_path, sess_options=dml_opts, providers=dml_providers
                )
                self.mark_used()
                logger.debug(format_logfmt("YoloSessionReady", provider="DmlExecutionProvider"))
                return
            except (RuntimeError, ValueError, OSError) as dml_exc:
                logger.warning(
                    "DirectML initialization failed for YOLO11 ('%s'); falling back to CPUExecutionProvider.",
                    dml_exc,
                )

        cpu_opts = self._build_session_options(
            ort, enable_mem_pattern=True, intra_op_threads=self._cpu_threads
        )
        try:
            self._session = ort.InferenceSession(
                self._model_path, sess_options=cpu_opts, providers=["CPUExecutionProvider"]
            )
            self.mark_used()
            logger.debug(
                format_logfmt("YoloSessionReady", provider="CPUExecutionProvider", threads=self._cpu_threads)
            )
        except Exception:
            logger.exception(format_logfmt("YoloSessionInitFailed", provider=self._provider))
            raise

    def _preprocess(
        self, image: Image.Image
    ) -> tuple[np.ndarray[Any, np.dtype[np.float32]], float, int, int]:
        """Resize image into letterboxed square tensor matching input_size."""
        orig_w, orig_h = image.size
        scale, pad_x, pad_y = compute_letterbox_params(
            orig_w, orig_h, target_size=self._input_size
        )

        logger.debug(
            "YOLO11 Letterbox prep: orig=(%d, %d), scale=%.4f, pad=(%d, %d), target_size=%d",
            orig_w,
            orig_h,
            scale,
            pad_x,
            pad_y,
            self._input_size,
        )

        new_w = round(orig_w * scale)
        new_h = round(orig_h * scale)

        resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)

        # Standard YOLO letterbox padding with gray (114, 114, 114)
        padded = Image.new("RGB", (self._input_size, self._input_size), (114, 114, 114))
        padded.paste(resized, (pad_x, pad_y))

        # Convert to CHW float32 [0.0, 1.0] normalized array
        img_np = np.array(padded, dtype=np.float32) / 255.0
        img_chw = np.transpose(img_np, (2, 0, 1))
        tensor = np.expand_dims(img_chw, axis=0)

        return tensor, scale, pad_x, pad_y

    async def detect(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> list[DetectedBubble]:
        """Detect speech bubbles from raw image bytes and return normalized [0, 1000] boxes with polygons."""
        bubbles, _ = await self.detect_layout(image_bytes, original_width, original_height)
        return bubbles

    async def detect_layout(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> tuple[list[DetectedBubble], list[DetectedPanel]]:
        """Detect speech bubbles and manga panels simultaneously (legacy pseudo-bubble mode)."""
        layout = await self._detect_internal(
            image_bytes, original_width, original_height, synthesize_orphan_bubbles=True
        )
        return layout.bubbles, layout.panels

    async def detect_full_layout(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> PageLayoutDetections:
        """Detect speech bubbles, panels, SFX exclusion boxes, and orphan texts without prose fragmentation."""
        return await self._detect_internal(
            image_bytes, original_width, original_height, synthesize_orphan_bubbles=False
        )

    async def _detect_internal(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
        synthesize_orphan_bubbles: bool,
    ) -> PageLayoutDetections:
        self._ensure_session()

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = image.size
        if original_width > 0:
            w = original_width
        if original_height > 0:
            h = original_height

        tensor, scale, pad_x, pad_y = self._preprocess(image)

        session = self._session
        if session is None:
            raise RuntimeError("Inference session failed to initialize.")

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: tensor})
        self.mark_used()

        return self._parse_full_outputs(
            outputs,
            scale,
            pad_x,
            pad_y,
            w,
            h,
            synthesize_orphan_bubbles=synthesize_orphan_bubbles,
        )

    def _parse_outputs(
        self,
        outputs: list[Any],
        scale: float,
        pad_x: int,
        pad_y: int,
        orig_w: int,
        orig_h: int,
    ) -> tuple[list[DetectedBubble], list[DetectedPanel]]:
        """Legacy wrapper parsing YOLO11 outputs with orphan pseudo-bubble synthesis enabled."""
        layout = self._parse_full_outputs(
            outputs,
            scale,
            pad_x,
            pad_y,
            orig_w,
            orig_h,
            synthesize_orphan_bubbles=True,
        )
        return layout.bubbles, layout.panels

    def _nms_boxes_to_1000(
        self,
        candidates: list[list[int]],
        scores: list[float],
        threshold: float,
        scale: float,
        pad_x: int,
        pad_y: int,
        orig_w: int,
        orig_h: int,
    ) -> list[tuple[tuple[int, int, int, int], float]]:
        """Run OpenCV NMS on [x, y, w, h] model-space boxes and convert to canonical [0, 1000]."""
        if not candidates:
            return []
        indices = cv2.dnn.NMSBoxes(
            bboxes=candidates,
            scores=scores,
            score_threshold=threshold,
            nms_threshold=self._iou_threshold,
        )
        flat = [int(i) for i in np.asarray(indices).flatten()] if len(indices) > 0 else []
        results: list[tuple[tuple[int, int, int, int], float]] = []
        for idx in flat:
            x, y, bw, bh = candidates[idx]
            ox1, oy1 = invert_letterbox_coords(float(x), float(y), scale, pad_x, pad_y, orig_w, orig_h)
            ox2, oy2 = invert_letterbox_coords(float(x + bw), float(y + bh), scale, pad_x, pad_y, orig_w, orig_h)
            box_1000 = normalize_box_to_1000(
                min(oy1, oy2),
                min(ox1, ox2),
                max(oy1, oy2),
                max(ox1, ox2),
                orig_w,
                orig_h,
            )
            results.append((box_1000, round(scores[idx], 4)))
        return results

    def _parse_full_outputs(
        self,
        outputs: list[Any],
        scale: float,
        pad_x: int,
        pad_y: int,
        orig_w: int,
        orig_h: int,
        synthesize_orphan_bubbles: bool = False,
    ) -> PageLayoutDetections:
        """Parse YOLO11 outputs: decode bubbles, proto masks, panels, SFX exclusion boxes, and child texts."""
        if not outputs:
            return PageLayoutDetections(bubbles=[], panels=[], sfx_boxes=[], orphan_texts=[])

        raw_pred = np.asarray(outputs[0])
        if raw_pred.size == 0:
            return PageLayoutDetections(bubbles=[], panels=[], sfx_boxes=[], orphan_texts=[])

        # YOLO11 segmentation output0: (1, 40, num_anchors) -> Transpose to (num_anchors, 40)
        if raw_pred.ndim == 3:
            raw_pred = raw_pred[0]
        if raw_pred.shape[0] == 40 or (raw_pred.shape[0] < raw_pred.shape[1] and raw_pred.shape[1] > 40):
            raw_pred = raw_pred.T

        _num_anchors, num_features = raw_pred.shape
        if num_features < 8:
            logger.warning("Unexpected YOLO11 output feature dimension: %d", num_features)
            return PageLayoutDetections(bubbles=[], panels=[], sfx_boxes=[], orphan_texts=[])

        # Prototype masks: output1 shape (1, 32, 256, 256) -> (32, 256, 256)
        protos: np.ndarray[Any, np.dtype[np.float32]] | None = None
        if len(outputs) > 1:
            raw_protos = np.asarray(outputs[1])
            if raw_protos.ndim == 4:
                raw_protos = raw_protos[0]
            if raw_protos.ndim == 3 and raw_protos.shape[0] == 32:
                protos = raw_protos.astype(np.float32)

        # Classes: 0: bubble, 1: panel, 2: sfx, 3: text
        bubble_candidates: list[list[int]] = []
        bubble_scores: list[float] = []
        bubble_coeffs: list[np.ndarray[Any, np.dtype[np.float32]]] = []
        bubble_boxes_model: list[tuple[float, float, float, float]] = []

        panel_candidates: list[list[int]] = []
        panel_scores: list[float] = []

        sfx_candidates: list[list[int]] = []
        sfx_scores: list[float] = []

        text_candidates: list[list[int]] = []
        text_scores: list[float] = []

        for row in raw_pred:
            cx, cy, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            score_bubble = float(row[4])
            score_panel = float(row[5])
            score_sfx = float(row[6]) if num_features > 6 else 0.0
            score_text = float(row[7]) if num_features > 7 else 0.0

            bx1 = cx - w / 2.0
            by1 = cy - h / 2.0
            bx2 = cx + w / 2.0
            by2 = cy + h / 2.0

            box_nms = [round(bx1), round(by1), round(w), round(h)]

            if score_bubble >= self._bubble_threshold:
                bubble_candidates.append(box_nms)
                bubble_scores.append(score_bubble)
                bubble_boxes_model.append((bx1, by1, bx2, by2))
                if num_features >= 40:
                    bubble_coeffs.append(row[8:40].astype(np.float32))

            if score_panel >= self._panel_threshold:
                panel_candidates.append(box_nms)
                panel_scores.append(score_panel)

            if score_sfx >= self._sfx_threshold:
                sfx_candidates.append(box_nms)
                sfx_scores.append(score_sfx)

            if score_text >= self._text_threshold:
                text_candidates.append(box_nms)
                text_scores.append(score_text)

        logger.debug(
            "YOLO11 raw candidates (bubble_th=%.2f, text_th=%.2f, panel_th=%.2f, sfx_th=%.2f): bubbles=%d, panels=%d, sfx=%d, texts=%d",
            self._bubble_threshold,
            self._text_threshold,
            self._panel_threshold,
            self._sfx_threshold,
            len(bubble_candidates),
            len(panel_candidates),
            len(sfx_candidates),
            len(text_candidates),
        )

        # 1. NMS for bubbles (preserves proto-mask coefficients per index)
        kept_bubbles: list[DetectedBubble] = []
        if bubble_candidates:
            indices_b = cv2.dnn.NMSBoxes(
                bboxes=bubble_candidates,
                scores=bubble_scores,
                score_threshold=self._bubble_threshold,
                nms_threshold=self._iou_threshold,
            )
            bubble_indices = [int(i) for i in np.asarray(indices_b).flatten()] if len(indices_b) > 0 else []

            for idx in bubble_indices:
                score = bubble_scores[idx]
                box_model = bubble_boxes_model[idx]
                bx1, by1, bx2, by2 = box_model

                orig_x1, orig_y1 = invert_letterbox_coords(bx1, by1, scale, pad_x, pad_y, orig_w, orig_h)
                orig_x2, orig_y2 = invert_letterbox_coords(bx2, by2, scale, pad_x, pad_y, orig_w, orig_h)

                box_1000 = normalize_box_to_1000(
                    min(orig_y1, orig_y2),
                    min(orig_x1, orig_x2),
                    max(orig_y1, orig_y2),
                    max(orig_x1, orig_x2),
                    orig_w,
                    orig_h,
                )

                if self._return_polygon and protos is not None and idx < len(bubble_coeffs):
                    polygon = extract_rdp_polygon(
                        bubble_coeffs[idx],
                        protos,
                        box_model,
                        scale,
                        pad_x,
                        pad_y,
                        orig_w,
                        orig_h,
                    )
                else:
                    polygon = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]

                kept_bubbles.append(
                    DetectedBubble(
                        id=str(len(kept_bubbles) + 1),
                        box_2d=box_1000,
                        polygon=polygon,
                        confidence=round(score, 4),
                    )
                )

        # 2. NMS for texts, panels, and SFX exclusion mask
        kept_texts = [
            DetectedText(box_2d=box, confidence=conf)
            for box, conf in self._nms_boxes_to_1000(
                text_candidates, text_scores, self._text_threshold, scale, pad_x, pad_y, orig_w, orig_h
            )
        ]
        kept_panels = [
            DetectedPanel(box_2d=box, confidence=conf)
            for box, conf in self._nms_boxes_to_1000(
                panel_candidates, panel_scores, self._panel_threshold, scale, pad_x, pad_y, orig_w, orig_h
            )
        ]
        kept_sfx = [
            box
            for box, _conf in self._nms_boxes_to_1000(
                sfx_candidates, sfx_scores, self._sfx_threshold, scale, pad_x, pad_y, orig_w, orig_h
            )
        ]

        # 3. Assign child texts to bubbles (optionally keeping orphans separate for hybrid clustering)
        if synthesize_orphan_bubbles:
            bubbles_with_texts = assign_child_texts_to_bubbles(
                kept_bubbles, kept_texts, synthesize_orphan_bubbles=True
            )
            orphan_texts: list[DetectedText] = []
        else:
            bubbles_with_texts, orphan_texts = assign_child_texts_with_orphans(kept_bubbles, kept_texts)

        # 4. 2-Tier Japanese Manga Reading Order Sorting (Panel -> In-Panel 1.5Y - X)
        final_bubbles = MangaReadingOrderSorter.sort(bubbles_with_texts, kept_panels)

        logger.debug(
            format_logfmt(
                "YoloDetectionsFinal",
                bubbles=len(final_bubbles),
                panels=len(kept_panels),
                sfx=len(kept_sfx),
                texts=len(kept_texts),
                orphans=len(orphan_texts),
            )
        )

        return PageLayoutDetections(
            bubbles=final_bubbles,
            panels=kept_panels,
            sfx_boxes=kept_sfx,
            orphan_texts=orphan_texts,
        )
