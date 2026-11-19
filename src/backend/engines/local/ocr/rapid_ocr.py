"""RapidOCR (PP-OCRv6_medium & Korean PP-OCRv5 ONNX) adapter with DirectML GPU acceleration."""

from __future__ import annotations

import importlib
import io
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from PIL import Image

from src.backend.engines.local.ocr.text_assembler import (
    ParagraphCluster,
    assemble_comic_lines,
    clean_cjk_text,
    cluster_lines_bidirectional,
    order_bubble_lines_bidirectional,
    parse_ocr_entry,
)
from src.backend.logging import get_logger

if TYPE_CHECKING:
    from src.backend.detection.assembler import BubbleWorkItem

logger = get_logger("ocr.rapid")


def to_bgr_array(image_np: np.ndarray[Any, Any] | Image.Image) -> np.ndarray[Any, Any]:
    """Convert PIL RGB Image or RGB numpy array to OpenCV BGR numpy array."""
    if isinstance(image_np, Image.Image):
        rgb = np.array(image_np.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if image_np.ndim == 2:
        return cv2.cvtColor(image_np, cv2.COLOR_GRAY2BGR)
    if image_np.shape[2] == 4:
        return cv2.cvtColor(image_np, cv2.COLOR_RGBA2BGR)
    return cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)


class RapidOCRAdapter:
    """Multilingual OCR adapter wrapping rapidocr>=3.9.1 with explicit DirectML ORT session injection."""

    def __init__(
        self,
        rapidocr_engine: Any | None = None,
        execution_provider: str | None = None,
    ) -> None:
        self._engines: dict[str, Any] = {}
        self._custom_engine_provided = rapidocr_engine is not None
        self._execution_provider_override = execution_provider
        self._det_engine: Any | None = None
        self._rec_engine: Any | None = None
        self._ko_rec_engine: Any | None = None
        self._ko_load_attempted = False
        if rapidocr_engine is not None:
            self._engines["default"] = rapidocr_engine

    @property
    def name(self) -> str:
        """OCR adapter identifier."""
        return "rapidocr"

    @property
    def _engine(self) -> Any | None:
        """Backwards-compatibility accessor for injected or composite default engine."""
        return self._engines.get("default")

    @property
    def supports_full_page(self) -> bool:
        """RapidOCR supports single-pass full-page text detection and recognition."""
        return True

    @property
    def supports_split_pipeline(self) -> bool:
        """True when native PP-OCRv6 split det/rec pipeline is active (no legacy mock override)."""
        return not self._custom_engine_provided and not any(
            k in self._engines for k in ("default", "ja")
        )

    async def is_available(self) -> bool:
        """Check whether RapidOCR runtime is importable or an engine is already loaded."""
        if self._engines or (self._det_engine is not None and self._rec_engine is not None):
            return True
        try:
            importlib.import_module("rapidocr")
            return True
        except ImportError:
            return False

    @staticmethod
    def _normalize_lang(lang: str | None) -> str:
        """Normalize legacy language identifier to internal key."""
        if not lang or lang == "auto":
            return "default"
        code = lang.lower().strip()
        if code in ("ko", "korean"):
            return "ko"
        if code in ("ja", "japanese"):
            return "ja"
        return "default"

    @staticmethod
    def _create_ort_session(model_path: str, execution_provider: str = "directml") -> Any:
        """Create onnxruntime InferenceSession bypassing rapidocr DictConfig DML bug."""
        ort = importlib.import_module("onnxruntime")
        if execution_provider == "directml":
            providers: list[Any] = [
                ("DmlExecutionProvider", {"device_id": 0}),
                "CPUExecutionProvider",
            ]
            try:
                sess = ort.InferenceSession(model_path, providers=providers)
                active = sess.get_providers()
                logger.debug("Loaded ORT session '%s' with providers=%s", Path(model_path).name, active)
                return sess
            except (RuntimeError, ValueError, OSError) as dml_exc:
                logger.warning(
                    "DirectML initialization failed for '%s' (%s); falling back to CPUExecutionProvider.",
                    Path(model_path).name,
                    dml_exc,
                )
        return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    def _load_rapidocr_base_cfg(self) -> tuple[Any, Path, Any, Any, Any]:
        """Import rapidocr submodules and load canonical OmegaConf base config."""
        try:
            rapid_pkg = importlib.import_module("rapidocr")
            det_mod = importlib.import_module("rapidocr.ch_ppocr_det.main")
            rec_mod = importlib.import_module("rapidocr.ch_ppocr_rec.main")
            parse_mod = importlib.import_module("rapidocr.utils.parse_parameters")
            omega_mod = importlib.import_module("omegaconf")
        except (ImportError, AttributeError) as exc:
            logger.exception("Failed to initialize RapidOCR engine")
            raise RuntimeError(
                f"Failed to initialize RapidOCR engine: {exc}. "
                "Ensure 'rapidocr>=3.9.1' is installed in the environment."
            ) from exc

        cfg_path = Path(str(rapid_pkg.__file__)).resolve().parent / "config.yaml"
        base_cfg = parse_mod.ParseParams.load(cfg_path)
        return (
            base_cfg,
            Path(str(rapid_pkg.__file__)).resolve().parent / "models",
            det_mod.TextDetector,
            rec_mod.TextRecognizer,
            omega_mod.OmegaConf,
        )

    def _ensure_det_and_rec(self) -> None:
        """Lazily initialize PP-OCRv6_det_medium and PP-OCRv6_rec_medium DirectML engines."""
        if self._det_engine is not None and self._rec_engine is not None:
            return

        base_cfg, default_models_dir, text_det_cls, text_rec_cls, omegaconf_cls = (
            self._load_rapidocr_base_cfg()
        )
        from src.backend.config import Settings
        from src.backend.detection.downloader import ensure_ocr_model_files

        settings = Settings()
        provider = self._execution_provider_override or settings.inkshift_local_execution_provider
        det_path = ensure_ocr_model_files(
            "det",
            dest_path=settings.inkshift_local_ocr_det_model_path,
            auto_download=settings.inkshift_auto_download_models,
        )
        rec_path = ensure_ocr_model_files(
            "rec",
            dest_path=settings.inkshift_local_ocr_rec_model_path,
            auto_download=settings.inkshift_auto_download_models,
        )
        if det_path is None or rec_path is None:
            raise RuntimeError(
                "PP-OCRv6_medium model weights missing and auto-download failed. "
                "Run 'python scripts/download_models.py' to provision OCR weights."
            )

        det_sess = self._create_ort_session(str(det_path), execution_provider=provider)
        rec_sess = self._create_ort_session(str(rec_path), execution_provider=provider)

        det_container = omegaconf_cls.to_container(base_cfg.Det, resolve=False)
        det_container.update({
            "limit_side_len": 1920,
            "limit_type": "max",
            "thresh": 0.2,
            "box_thresh": 0.35,
            "unclip_ratio": 1.8,
            "engine_cfg": base_cfg.EngineConfig.onnxruntime,
            "model_root_dir": default_models_dir,
            "model_path": str(det_path),
            "session": det_sess,
        })
        cfg_det = omegaconf_cls.create(det_container, flags={"allow_objects": True})

        rec_container = omegaconf_cls.to_container(base_cfg.Rec, resolve=False)
        rec_container.update({
            "engine_cfg": base_cfg.EngineConfig.onnxruntime,
            "model_root_dir": default_models_dir,
            "model_path": str(rec_path),
            "font_path": None,
            "session": rec_sess,
        })
        cfg_rec = omegaconf_cls.create(rec_container, flags={"allow_objects": True})

        self._det_engine = text_det_cls(cfg_det)
        self._rec_engine = text_rec_cls(cfg_rec)
        logger.info(
            "Initialized PP-OCRv6_medium (det=%s, rec=%s) with providers det=%s, rec=%s",
            det_path.name,
            rec_path.name,
            det_sess.get_providers()[0],
            rec_sess.get_providers()[0],
        )

    def _ensure_ko_rec(self) -> Any | None:
        """Lazily initialize Korean PP-OCRv5 mobile recognizer on demand."""
        if self._ko_rec_engine is not None:
            return self._ko_rec_engine
        if self._ko_load_attempted:
            return None
        self._ko_load_attempted = True

        base_cfg, default_models_dir, _det_cls, text_rec_cls, omegaconf_cls = (
            self._load_rapidocr_base_cfg()
        )
        from src.backend.config import Settings
        from src.backend.detection.downloader import ensure_ocr_model_files

        settings = Settings()
        ko_path = ensure_ocr_model_files(
            "ko",
            dest_path=settings.inkshift_local_ocr_ko_model_path,
            auto_download=settings.inkshift_auto_download_models,
        )
        if ko_path is None or not ko_path.exists():
            logger.warning("Korean OCR weights unavailable; falling back to default PP-OCRv6 recognizer.")
            return None

        provider = self._execution_provider_override or settings.inkshift_local_execution_provider
        ko_sess = self._create_ort_session(str(ko_path), execution_provider=provider)
        ko_container = omegaconf_cls.to_container(base_cfg.Rec, resolve=False)
        ko_container.update({
            "engine_cfg": base_cfg.EngineConfig.onnxruntime,
            "model_root_dir": default_models_dir,
            "model_path": str(ko_path),
            "font_path": None,
            "session": ko_sess,
        })
        cfg_ko = omegaconf_cls.create(ko_container, flags={"allow_objects": True})
        self._ko_rec_engine = text_rec_cls(cfg_ko)
        self._engines["ko"] = self._ko_rec_engine
        logger.info(
            "Lazy-loaded Korean recognizer '%s' with provider=%s",
            ko_path.name,
            ko_sess.get_providers()[0],
        )
        return self._ko_rec_engine

    def detect_text_boxes(self, image_bgr: np.ndarray[Any, Any]) -> list[np.ndarray[Any, Any]]:
        """Run DBNet (PP-OCRv6_det_medium) once on a BGR image and return 4-point quads."""
        self._ensure_det_and_rec()
        if self._det_engine is None:
            return []

        h, w = image_bgr.shape[:2]
        pad_h = max(0, 32 - h)
        pad_w = max(0, 32 - w)
        if pad_h > 0 or pad_w > 0:
            input_img = cv2.copyMakeBorder(
                image_bgr, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=(255, 255, 255)
            )
        else:
            input_img = image_bgr

        det_res = self._det_engine(input_img)
        if det_res is None or det_res.boxes is None or len(det_res.boxes) == 0:
            return []

        quads: list[np.ndarray[Any, Any]] = []
        for box in det_res.boxes:
            pts = np.asarray(box, dtype=np.float32).copy()
            pts[:, 0] = np.clip(pts[:, 0], 0.0, float(w))
            pts[:, 1] = np.clip(pts[:, 1], 0.0, float(h))
            quads.append(pts)
        return quads

    @staticmethod
    def crop_quad(
        image_bgr: np.ndarray[Any, Any],
        quad: np.ndarray[Any, Any],
    ) -> np.ndarray[Any, Any]:
        """Extract perspective-rectified BGR crop (auto-rotates vertical quads 90 deg CCW)."""
        pimg = importlib.import_module("rapidocr.utils.process_img")
        cropped = pimg.get_rotate_crop_image(image_bgr, quad.astype(np.float32))
        return np.asarray(cropped)

    def recognize_crops(
        self,
        crops_bgr: list[np.ndarray[Any, Any]],
        use_korean: bool = False,
    ) -> list[tuple[str, float]]:
        """Recognize a batch of BGR crops in one ONNX Runtime batch call."""
        if not crops_bgr:
            return []

        self._ensure_det_and_rec()
        rec_mod = importlib.import_module("rapidocr.ch_ppocr_rec.main")
        text_rec_input_cls = rec_mod.TextRecInput

        if use_korean:
            rec_engine = self._ensure_ko_rec()
            if rec_engine is None:
                return [("", 0.0) for _ in crops_bgr]
        else:
            rec_engine = self._rec_engine

        if rec_engine is None:
            return [("", 0.0) for _ in crops_bgr]

        valid_indices: list[int] = []
        valid_crops: list[np.ndarray[Any, Any]] = []
        for idx, crop in enumerate(crops_bgr):
            if crop.size > 0 and crop.shape[0] > 0 and crop.shape[1] > 0:
                valid_indices.append(idx)
                valid_crops.append(crop)

        results: list[tuple[str, float]] = [("", 0.0) for _ in crops_bgr]
        if not valid_crops:
            return results

        rec_out = rec_engine(text_rec_input_cls(img=valid_crops))
        txts = rec_out.txts or ()
        scores = rec_out.scores or ()
        for pos, orig_idx in enumerate(valid_indices):
            txt = str(txts[pos]).strip() if pos < len(txts) else ""
            conf = float(scores[pos]) if pos < len(scores) else 0.0
            results[orig_idx] = (txt, conf)
        return results

    def recheck_ambiguous_square_bubble(
        self,
        image_bgr: np.ndarray[Any, Any],
        pixel_box: tuple[int, int, int, int],
        use_korean: bool = False,
    ) -> list[tuple[np.ndarray[Any, Any], str, float]] | None:
        """Rotate a tight square CJK bubble 90 deg CCW so vertical columns split horizontally cleanly."""
        h_img, w_img = image_bgr.shape[:2]
        y1 = max(0, pixel_box[0])
        x1 = max(0, pixel_box[1])
        y2 = min(h_img, pixel_box[2])
        x2 = min(w_img, pixel_box[3])
        crop_w = x2 - x1
        crop_h = y2 - y1
        if crop_w < 16 or crop_h < 16:
            return None

        bubble_bgr = image_bgr[y1:y2, x1:x2]
        rot_bgr = cv2.rotate(bubble_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
        rot_quads = self.detect_text_boxes(rot_bgr)
        if not rot_quads:
            return None

        rot_crops = [self.crop_quad(rot_bgr, q) for q in rot_quads]
        recognized = self.recognize_crops(rot_crops, use_korean=use_korean)

        mapped: list[tuple[np.ndarray[Any, Any], str, float]] = []
        for quad, (txt, conf) in zip(rot_quads, recognized):
            if not txt:
                continue
            # Invert ROTATE_90_COUNTERCLOCKWISE: x_orig = x1 + (crop_w - y_rot), y_orig = y1 + x_rot
            orig_pts = np.empty_like(quad, dtype=np.float32)
            orig_pts[:, 0] = np.clip(float(x1) + (float(crop_w) - quad[:, 1]), 0.0, float(w_img))
            orig_pts[:, 1] = np.clip(float(y1) + quad[:, 0], 0.0, float(h_img))
            mapped.append((orig_pts, txt, conf))

        return mapped or None

    def _run_full_image_lines(
        self,
        image_bgr: np.ndarray[Any, Any],
        use_korean: bool = False,
    ) -> list[list[Any]]:
        """Execute split det -> crop -> rec and return legacy [[quad_list, text, score], ...] structure."""
        quads = self.detect_text_boxes(image_bgr)
        if not quads:
            return []
        crops = [self.crop_quad(image_bgr, q) for q in quads]
        rec_res = self.recognize_crops(crops, use_korean=use_korean)
        lines: list[list[Any]] = []
        for quad, (txt, conf) in zip(quads, rec_res):
            if txt:
                lines.append([quad.tolist(), txt, conf])
        return lines

    def _get_legacy_mock_engine(self, lang: str = "default") -> Any | None:
        """Return manually injected mock callable when unit tests bypass native split PP-OCRv6."""
        target = self._normalize_lang(lang)
        if target in self._engines:
            return self._engines[target]
        if "default" in self._engines:
            return self._engines["default"]
        return None

    async def recognize_batch(self, image_crops: list[bytes], lang: str = "auto") -> list[str]:
        """Extract text from a list of cropped speech bubble images."""
        if not image_crops:
            return []

        mock_engine = self._get_legacy_mock_engine(lang)
        use_split = mock_engine is None and self.supports_split_pipeline
        use_korean = self._normalize_lang(lang) == "ko"

        t0 = time.perf_counter()
        results: list[str] = []
        for crop_bytes in image_crops:
            if not crop_bytes:
                results.append("")
                continue

            try:
                img = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
            except (OSError, ValueError):
                results.append("")
                continue

            if use_split:
                img_bgr = to_bgr_array(img)
                ocr_result = self._run_full_image_lines(img_bgr, use_korean=use_korean)
            else:
                img_np = np.array(img)
                ocr_output = mock_engine(img_np) if mock_engine is not None else None
                ocr_result = (
                    ocr_output[0]
                    if ocr_output and isinstance(ocr_output, (list, tuple)) and isinstance(ocr_output[0], list)
                    else []
                )

            if not ocr_result:
                results.append("")
                continue

            entries = [
                entry
                for item in ocr_result
                if len(item) >= 2 and item[1]
                and (entry := parse_ocr_entry(item[0], str(item[1]), float(item[2]) if len(item) > 2 else 1.0))
                is not None
            ]
            if entries:
                assembled, _direction = order_bubble_lines_bidirectional(entries)
            else:
                assembled = assemble_comic_lines([str(item[1]) for item in ocr_result if len(item) >= 2 and item[1]])

            if self._normalize_lang(lang) in ("ja", "zh"):
                assembled = clean_cjk_text(assembled)
            results.append(assembled)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "RapidOCR batch completed: %d crops processed in %.2fms (%d non-empty)",
            len(image_crops),
            elapsed_ms,
            sum(1 for r in results if r.strip()),
        )
        return results

    async def recognize_full_page(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
        lang: str = "auto",
    ) -> list[str]:
        """Recognize text lines across uncropped page and map into work items via spatial containment."""
        if not work_items:
            return []

        mock_engine = self._get_legacy_mock_engine(lang)
        t0 = time.perf_counter()

        if mock_engine is not None or not self.supports_split_pipeline:
            img_arr = np.array(image_np.convert("RGB")) if isinstance(image_np, Image.Image) else image_np
            ocr_output = mock_engine(img_arr) if mock_engine is not None else None
            ocr_result = ocr_output[0] if (ocr_output and ocr_output[0] is not None) else []
        else:
            img_bgr = to_bgr_array(image_np)
            ocr_result = self._run_full_image_lines(
                img_bgr, use_korean=(self._normalize_lang(lang) == "ko")
            )

        if not isinstance(ocr_result, list):
            ocr_result = []

        assigned_lines: dict[int, list[dict[str, Any]]] = {idx: [] for idx in range(len(work_items))}
        boxes_canonical = [item.crop_box for item in work_items]
        margin = 6

        for item in ocr_result:
            if not item or len(item) < 2:
                continue
            entry = parse_ocr_entry(
                item[0],
                str(item[1]).strip(),
                float(item[2]) if len(item) > 2 else 1.0,
            )
            if entry is None or not entry["text"]:
                continue

            norm_cx = (float(entry["cx"]) / max(1, image_width)) * 1000.0
            norm_cy = (float(entry["cy"]) / max(1, image_height)) * 1000.0

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
                assigned_lines[best_idx].append(entry)

        results: list[str] = []
        for idx in range(len(work_items)):
            assembled, _dir = order_bubble_lines_bidirectional(assigned_lines[idx])
            results.append(assembled)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "RapidOCR full-page completed: %d text elements mapped to %d bubbles in %.2fms (%d non-empty)",
            len(ocr_result),
            len(work_items),
            elapsed_ms,
            sum(1 for r in results if r.strip()),
        )
        return results

    async def recognize_direct_paragraphs(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        image_width: int,
        image_height: int,
        lang: str = "auto",
    ) -> list[ParagraphCluster]:
        """Detect and recognize full-page text directly into bi-directional clustered paragraphs."""
        mock_engine = self._get_legacy_mock_engine(lang)
        t0 = time.perf_counter()

        if mock_engine is not None or not self.supports_split_pipeline:
            img_arr = np.array(image_np.convert("RGB")) if isinstance(image_np, Image.Image) else image_np
            ocr_output = mock_engine(img_arr) if mock_engine is not None else None
            ocr_result = ocr_output[0] if (ocr_output and ocr_output[0] is not None) else []
        else:
            img_bgr = to_bgr_array(image_np)
            ocr_result = self._run_full_image_lines(
                img_bgr, use_korean=(self._normalize_lang(lang) == "ko")
            )

        if not isinstance(ocr_result, list):
            ocr_result = []

        paragraphs = cluster_lines_bidirectional(
            raw_ocr_lines=ocr_result,
            image_width=image_width,
            image_height=image_height,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "RapidOCR direct paragraphs completed: %d lines clustered into %d paragraphs in %.2fms",
            len(ocr_result),
            len(paragraphs),
            elapsed_ms,
        )
        return paragraphs
