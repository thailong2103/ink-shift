"""MangaOCR adapter for specialized Japanese vertical and horizontal manga text recognition."""

from __future__ import annotations

import importlib
import io
import os
import time
from typing import Any

from PIL import Image

from src.backend.config import Settings
from src.backend.engines.local.ocr.text_assembler import clean_japanese_text
from src.backend.logging import get_logger

logger = get_logger("ocr.manga")


class MangaOCRAdapter:
    """Specialized Japanese OCR adapter utilizing MangaOCR (Vision-Encoder-Decoder)."""

    def __init__(
        self,
        manga_ocr_engine: Any | None = None,
        model_path: str | None = None,
    ) -> None:
        settings = Settings()
        self._model_path = (
            model_path
            if model_path is not None
            else (
                settings.inkshift_local_manga_ocr_model_path
                or os.path.join(settings.inkshift_local_model_dir, "manga_ocr.onnx")
            )
        )
        self._engine = manga_ocr_engine

    @property
    def name(self) -> str:
        """OCR adapter identifier."""
        return "manga-ocr"

    @property
    def supports_full_page(self) -> bool:
        """MangaOCR requires cropped bubble images; full-page recognition is unsupported."""
        return False

    async def is_available(self) -> bool:
        """Check whether MangaOCR engine is loaded, importable, or model weights exist."""
        if self._engine is not None:
            return True
        if os.path.exists(self._model_path):
            return True
        try:
            importlib.import_module("manga_ocr")
            return True
        except ImportError:
            return False

    def _ensure_engine(self) -> None:
        """Lazily initialize MangaOCR engine."""
        if self._engine is not None:
            return

        logger.debug("Initializing MangaOCR engine (lazy model loading)...")
        # Strategy 1: Try importing standard manga_ocr package
        try:
            manga_module = importlib.import_module("manga_ocr")
            manga_cls = manga_module.MangaOcr
            self._engine = manga_cls()
            logger.debug("MangaOCR initialized successfully via python library.")
            return
        except (ImportError, AttributeError):
            pass

        # Strategy 2: Check if ONNX model weights exist
        if os.path.exists(self._model_path):
            try:
                ort_module = importlib.import_module("onnxruntime")
                ort_session = ort_module.InferenceSession(
                    self._model_path,
                    providers=[("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"],
                )
                self._engine = ort_session
                logger.debug(
                    "MangaOCR ONNX Session loaded from '%s' with DirectML/CPU providers.",
                    self._model_path,
                )
                return
            except (ImportError, AttributeError, RuntimeError, OSError) as err:
                logger.warning("Failed to load MangaOCR ONNX session: %s", err)

        logger.error(
            "Failed to initialize MangaOCR: 'manga-ocr' package missing and model weights not at '%s'",
            self._model_path,
        )
        raise RuntimeError(
            "Failed to initialize MangaOCR engine. "
            "Please ensure 'manga-ocr' package is installed or model weights exist at "
            f"'{self._model_path}'."
        )

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        """Transcribe Japanese text from speech bubble image crops."""
        if not image_crops:
            return []

        self._ensure_engine()
        engine = self._engine
        if engine is None:
            raise RuntimeError("MangaOCR engine failed to initialize.")

        t0 = time.perf_counter()
        results: list[str] = []
        for i, crop_bytes in enumerate(image_crops):
            if not crop_bytes:
                results.append("")
                continue

            try:
                img = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
            except (OSError, ValueError) as img_err:
                logger.debug("MangaOCR crop [%d/%d] invalid bytes: %s", i + 1, len(image_crops), img_err)
                results.append("")
                continue

            # Run inference via MangaOcr instance
            try:
                if callable(engine):
                    raw_text = engine(img)
                elif hasattr(engine, "predict"):
                    raw_text = engine.predict(img)
                else:
                    raw_text = ""

                cleaned = clean_japanese_text(str(raw_text))
                logger.debug(
                    "MangaOCR crop [%d/%d] (%dx%d px): raw='%s' -> cleaned='%s'",
                    i + 1,
                    len(image_crops),
                    img.width,
                    img.height,
                    str(raw_text)[:40],
                    cleaned[:40],
                )
                results.append(cleaned)
            except (RuntimeError, ValueError, TypeError, AttributeError) as inf_err:
                logger.debug("MangaOCR crop [%d/%d] inference error: %s", i + 1, len(image_crops), inf_err)
                results.append("")

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "MangaOCR batch finished: %d crops processed in %.2fms (transcribed %d/%d non-empty)",
            len(image_crops),
            elapsed_ms,
            sum(1 for r in results if r.strip()),
            len(image_crops),
        )
        return results
