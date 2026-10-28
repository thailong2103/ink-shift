"""Composite Local On-Device Translation Engine coordinating YOLO11, OCR, and Translation."""

from __future__ import annotations

import base64
import hashlib
import io
import time
from typing import Any

import numpy as np
from PIL import Image

from src.backend.detection.assembler import (
    BubbleWorkItem,
    assemble_translated_blocks,
    prepare_local_work_items,
)
from src.backend.detection.base import DetectedBubble
from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.engines.local.translator.base import BaseTextTranslator
from src.backend.engines.local.translator.registry import TranslatorRegistry
from src.backend.logging import format_logfmt, get_logger, track_stage
from src.backend.schemas.contract import (
    TranslationRequest,
    TranslationResponse,
)

logger = get_logger("local_engine")


class LocalTranslationEngine(BaseTranslationEngine):
    """Composite local manga translation engine running on DirectML."""

    def __init__(
        self,
        ocr_router: OCRRouter,
        translator_registry: TranslatorRegistry | None = None,
        translator: BaseTextTranslator | None = None,
        detector: Any = None,
        name: str = "local",
        default_ocr: str = "auto",
    ) -> None:
        """Initialize LocalTranslationEngine composite.

        Args:
            ocr_router: Intelligent OCR router (MangaOCR & RapidOCR).
            translator_registry: Registry of swappable text translators.
            translator: Single text translation adapter (for backwards compatibility).
            detector: Optional detector fallback for standalone usage.
            name: Engine identifier ('local').
            default_ocr: Default OCR strategy ('auto', 'manga-ocr', 'rapidocr').
        """
        self._name = name
        self._ocr_router = ocr_router
        self._detector = detector
        self._default_ocr = default_ocr

        if translator_registry is not None:
            self._translator_registry = translator_registry
        elif translator is not None:
            reg = TranslatorRegistry(default_translator_name=translator.name)
            reg.register(translator.name, translator)
            self._translator_registry = reg
        else:
            self._translator_registry = TranslatorRegistry()

    @property
    def name(self) -> str:
        """Unique engine identifier."""
        return self._name

    @property
    def translator_registry(self) -> TranslatorRegistry:
        """Configured TranslatorRegistry instance."""
        return self._translator_registry

    @property
    def translator(self) -> BaseTextTranslator:
        """Default text translator instance."""
        return self._translator_registry.get()

    async def is_available(self) -> bool:
        """Check whether OCR adapters and default translator are ready."""
        try:
            return await self._translator_registry.is_available()
        except (KeyError, RuntimeError, ValueError, TypeError, OSError):
            return False

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        """Execute complete local translation pipeline.

        Pipeline stages:
        1. Base64 image decode and SHA-256 hash validation
        2. Speech bubble and layout detection (skipped if pre-detected bubbles passed)
        3. Zero-copy cropping of detected dialogue regions
        4. Intelligent OCR script classification and transcription
        5. Batch text translation to target language via TranslatorRegistry
        6. Assembly into canonical TranslationResponse with boxes and polygons
        """
        start_time = time.perf_counter()

        # 1. Base64 Decode & Validation
        async with track_stage("1/4", "Giải mã ảnh & kiểm tra kích thước", logger) as stage_1:
            raw_b64 = request.image
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]

            try:
                image_bytes = base64.b64decode(raw_b64)
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                width, height = img.size
            except Exception as exc:
                raise ValueError(f"Failed to decode or parse image payload: {exc}") from exc

            page_hash = request.image_hash or hashlib.sha256(image_bytes).hexdigest()
            stage_1.info = f"Kích thước: {width}x{height}px | Hash: [{page_hash[:12]}...]"

        # 2. Bubble & Layout Detection (Option G1: skip if gateway provided bubbles)
        if bubbles is None:
            if self._detector is not None:
                async with track_stage("2/4", "Phát hiện bong bóng thoại & Layout (YOLO11s-seg)", logger) as stage_2:
                    bubbles = await self._detector.detect(image_bytes, width, height)
                    stage_2.info = f"Tìm thấy {len(bubbles)} bong bóng thoại"
            else:
                bubbles = []
        else:
            logger.debug(format_logfmt("GatewayDetectionsReceived", bubbles=len(bubbles)))

        if not bubbles:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(format_logfmt("NoBubblesDetected", action="SkipOCRAndTranslate"))
            return TranslationResponse(
                page_hash=page_hash,
                engine_used=self._name,
                execution_time_ms=elapsed_ms,
                from_cache=False,
                blocks=[],
            )

        # 3. OCR Transcription via Router (Single-pass Full-Page for Non-JA; Crop-based for JA)
        img_np = np.array(img)
        work_items = prepare_local_work_items(bubbles)

        ocr_mode = (
            request.source_lang
            if request.source_lang and request.source_lang != "auto"
            else self._default_ocr
        )
        chapter_id = request.chapter_url or page_hash

        async with track_stage("3/4", f"OCRRecognition (mode={ocr_mode})", logger) as stage_3:
            extracted_texts, ocr_engine_used = await self._ocr_router.recognize_routed_full_page(
                image_np=img_np,
                work_items=work_items,
                image_width=width,
                image_height=height,
                requested_model=ocr_mode,
                chapter_id=chapter_id,
            )
            non_empty_ocr = sum(1 for t in extracted_texts if t.strip())
            stage_3.info = f"adapter={ocr_engine_used}, valid={non_empty_ocr}/{len(extracted_texts)}"

        # Filter out empty or whitespace-only OCR results before translation
        valid_items: list[BubbleWorkItem] = []
        valid_raw_texts: list[str] = []
        for item, raw_text in zip(work_items, extracted_texts):
            if raw_text.strip():
                valid_items.append(item)
                valid_raw_texts.append(raw_text)

        if not valid_raw_texts:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(format_logfmt("EmptyOCROutput", action="SkipTranslate"))
            return TranslationResponse(
                page_hash=page_hash,
                engine_used=self._name,
                execution_time_ms=elapsed_ms,
                from_cache=False,
                blocks=[],
            )

        # 4. Batch Text Translation via TranslatorRegistry
        active_translator = self._translator_registry.get(request.translator)
        async with track_stage(
            "4/4",
            f"BatchTranslate ({len(valid_raw_texts)} blocks -> {request.target_lang} via {active_translator.name})",
            logger,
        ) as stage_4:
            translated_texts = await active_translator.translate_batch(
                valid_raw_texts,
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                model=request.model,
            )
            stage_4.info = f"translated={len(translated_texts)}"

        # 6. Assembly of Translated Blocks with Polygon and Parent Linking
        blocks = assemble_translated_blocks(
            bubbles=bubbles,
            translations=translated_texts,
            raw_texts=valid_raw_texts,
            work_items=valid_items,
        )

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(
            format_logfmt(
                "PipelineCompleted",
                engine=self._name,
                elapsed_ms=elapsed_ms,
                blocks=len(blocks),
            )
        )
        is_fallback = getattr(translated_texts, "is_fallback", False)
        # Additional safety heuristic: if all dialogue strings longer than 3 chars are identical, mark fallback
        if not is_fallback and len(valid_raw_texts) > 0 and request.target_lang == "vi" and request.source_lang in ("en", "ja", "zh", "ko"):
            meaningful = [(r.strip(), t.strip()) for r, t in zip(valid_raw_texts, translated_texts) if len(r.strip()) > 3]
            if meaningful and all(r.lower() == t.lower() for r, t in meaningful):
                is_fallback = True

        return TranslationResponse(
            page_hash=page_hash,
            engine_used=self._name,
            execution_time_ms=elapsed_ms,
            from_cache=False,
            is_fallback=is_fallback,
            blocks=blocks,
        )
