"""YOLO11s-seg ONNX instance segmentation detector with DirectML acceleration."""

from __future__ import annotations

import io
import os
from typing import Any

import cv2
import numpy as np
from PIL import Image

from src.backend.config import Settings
from src.backend.detection.base import (
    DetectedBubble,
    DetectedPanel,
    DetectedText,
)
from src.backend.detection.postprocess import (
    assign_child_texts_to_bubbles,
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
        auto_download: bool | None = None,
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
        self._session = onnx_session
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
        self._iou_threshold = iou_threshold
        self._return_polygon = return_polygon

    @property
    def name(self) -> str:
        """Detector identifier."""
        return "yolo11s-seg"

    async def is_available(self) -> bool:
        """Check whether session is ready or model weights exist on disk."""
        if self._session is not None:
            return True
        return os.path.exists(self._model_path)

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

        providers: list[Any]
        if self._provider == "directml":
            providers = [
                ("DmlExecutionProvider", {"device_id": 0}),
                "CPUExecutionProvider",
            ]
        else:
            providers = ["CPUExecutionProvider"]

        try:
            self._session = ort.InferenceSession(self._model_path, providers=providers)
            logger.debug(format_logfmt("YoloSessionReady", provider=self._provider))
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
        """Detect speech bubbles and manga panels simultaneously."""
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

        return self._parse_outputs(outputs, scale, pad_x, pad_y, w, h)

    def _parse_outputs(
        self,
        outputs: list[Any],
        scale: float,
        pad_x: int,
        pad_y: int,
        orig_w: int,
        orig_h: int,
    ) -> tuple[list[DetectedBubble], list[DetectedPanel]]:
        """Parse YOLO11 outputs: decode boxes, proto masks, filter SFX, and attach child texts."""
        if not outputs:
            return [], []

        raw_pred = np.asarray(outputs[0])
        if raw_pred.size == 0:
            return [], []

        # YOLO11 segmentation output0: (1, 40, num_anchors) -> Transpose to (num_anchors, 40)
        if raw_pred.ndim == 3:
            raw_pred = raw_pred[0]
        if raw_pred.shape[0] == 40 or (raw_pred.shape[0] < raw_pred.shape[1] and raw_pred.shape[1] > 40):
            raw_pred = raw_pred.T

        _num_anchors, num_features = raw_pred.shape
        if num_features < 8:
            logger.warning("Unexpected YOLO11 output feature dimension: %d", num_features)
            return [], []

        # Prototype masks: output1 shape (1, 32, 256, 256) -> (32, 256, 256)
        protos: np.ndarray[Any, np.dtype[np.float32]] | None = None
        if len(outputs) > 1:
            raw_protos = np.asarray(outputs[1])
            if raw_protos.ndim == 4:
                raw_protos = raw_protos[0]
            if raw_protos.ndim == 3 and raw_protos.shape[0] == 32:
                protos = raw_protos.astype(np.float32)

        # Classes: 0: bubble, 1: panel, 2: sfx (ignored), 3: text
        # Filter candidate bounding boxes per class
        bubble_candidates: list[list[int]] = []
        bubble_scores: list[float]
        bubble_coeffs: list[np.ndarray[Any, np.dtype[np.float32]]] = []
        bubble_boxes_model: list[tuple[float, float, float, float]] = []

        panel_candidates: list[list[int]] = []
        panel_scores: list[float] = []

        text_candidates: list[list[int]] = []
        text_scores: list[float] = []

        bubble_scores = []

        for row in raw_pred:
            cx, cy, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            score_bubble = float(row[4])
            score_panel = float(row[5])
            score_text = float(row[7]) if num_features > 7 else 0.0

            # Discard class 2 (sfx) unconditionally per ADR-007

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

            if score_text >= self._text_threshold:
                text_candidates.append(box_nms)
                text_scores.append(score_text)

        logger.debug(
            "YOLO11 raw candidates (bubble_th=%.2f, text_th=%.2f, panel_th=%.2f): bubbles=%d, panels=%d, texts=%d (sfx dropped)",
            self._bubble_threshold,
            self._text_threshold,
            self._panel_threshold,
            len(bubble_candidates),
            len(panel_candidates),
            len(text_candidates),
        )

        # 1. NMS for bubbles
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

                ymin_px = min(orig_y1, orig_y2)
                xmin_px = min(orig_x1, orig_x2)
                ymax_px = max(orig_y1, orig_y2)
                xmax_px = max(orig_x1, orig_x2)

                box_1000 = normalize_box_to_1000(ymin_px, xmin_px, ymax_px, xmax_px, orig_w, orig_h)

                # Decode RDP polygon from prototype masks
                if (
                    self._return_polygon
                    and protos is not None
                    and idx < len(bubble_coeffs)
                ):
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

                bubble_id = str(len(kept_bubbles) + 1)
                kept_bubbles.append(
                    DetectedBubble(
                        id=bubble_id,
                        box_2d=box_1000,
                        polygon=polygon,
                        confidence=round(score, 4),
                    )
                )

        # 2. NMS for texts
        kept_texts: list[DetectedText] = []
        if text_candidates:
            indices_t = cv2.dnn.NMSBoxes(
                bboxes=text_candidates,
                scores=text_scores,
                score_threshold=self._text_threshold,
                nms_threshold=self._iou_threshold,
            )
            text_indices = [int(i) for i in np.asarray(indices_t).flatten()] if len(indices_t) > 0 else []

            for idx in text_indices:
                score = text_scores[idx]
                tx, ty, tw, th = text_candidates[idx]
                tx1, ty1 = float(tx), float(ty)
                tx2, ty2 = float(tx + tw), float(ty + th)

                orig_x1, orig_y1 = invert_letterbox_coords(tx1, ty1, scale, pad_x, pad_y, orig_w, orig_h)
                orig_x2, orig_y2 = invert_letterbox_coords(tx2, ty2, scale, pad_x, pad_y, orig_w, orig_h)

                box_1000 = normalize_box_to_1000(
                    min(orig_y1, orig_y2),
                    min(orig_x1, orig_x2),
                    max(orig_y1, orig_y2),
                    max(orig_x1, orig_x2),
                    orig_w,
                    orig_h,
                )
                kept_texts.append(DetectedText(box_2d=box_1000, confidence=round(score, 4)))

        # 3. NMS for panels
        kept_panels: list[DetectedPanel] = []
        if panel_candidates:
            indices_p = cv2.dnn.NMSBoxes(
                bboxes=panel_candidates,
                scores=panel_scores,
                score_threshold=self._panel_threshold,
                nms_threshold=self._iou_threshold,
            )

            panel_indices = [int(i) for i in np.asarray(indices_p).flatten()] if len(indices_p) > 0 else []

            for idx in panel_indices:
                score = panel_scores[idx]
                px, py, pw, ph = panel_candidates[idx]
                px1, py1 = float(px), float(py)
                px2, py2 = float(px + pw), float(py + ph)

                orig_x1, orig_y1 = invert_letterbox_coords(px1, py1, scale, pad_x, pad_y, orig_w, orig_h)
                orig_x2, orig_y2 = invert_letterbox_coords(px2, py2, scale, pad_x, pad_y, orig_w, orig_h)

                box_1000 = normalize_box_to_1000(
                    min(orig_y1, orig_y2),
                    min(orig_x1, orig_x2),
                    max(orig_y1, orig_y2),
                    max(orig_x1, orig_x2),
                    orig_w,
                    orig_h,
                )
                kept_panels.append(DetectedPanel(box_2d=box_1000, confidence=round(score, 4)))

        # 4. Assign child texts to bubbles
        bubbles_with_texts = assign_child_texts_to_bubbles(kept_bubbles, kept_texts)

        # 5. 2-Tier Japanese Manga Reading Order Sorting (Panel -> In-Panel 1.5Y - X)
        final_bubbles = MangaReadingOrderSorter.sort(bubbles_with_texts, kept_panels)

        logger.debug(
            format_logfmt(
                "YoloDetectionsFinal",
                bubbles=len(final_bubbles),
                panels=len(kept_panels),
                texts=len(kept_texts),
            )
        )

        return final_bubbles, kept_panels
