"""Composite Local On-Device Translation Engine coordinating YOLO11, PP-OCRv6 Hybrid, and Translation."""

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
from src.backend.detection.base import DetectedBubble, PageLayoutDetections
from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.engines.local.ocr.text_assembler import ParagraphCluster
from src.backend.engines.local.translator.base import BaseTextTranslator
from src.backend.engines.local.translator.registry import TranslatorRegistry
from src.backend.logging import format_logfmt, get_logger, track_stage
from src.backend.schemas.contract import (
    TranslatedBlock,
    TranslationRequest,
    TranslationResponse,
)

logger = get_logger("local_engine")


def _reading_order_key(
    box_2d: tuple[int, int, int, int],
    kind: str,
    bubble_order_idx: int,
    use_rtl_manga_order: bool,
) -> tuple[float, float, float]:
    """Compute unified reading-order sort key across speech bubbles and residual text clusters."""
    ymin, xmin, ymax, xmax = box_2d
    cy = (ymin + ymax) / 2.0
    cx = (xmin + xmax) / 2.0
    if use_rtl_manga_order:
        # Preserve YOLO panel/RTL sort for bubbles via ordinal score when interleaving residuals
        if kind == "bubble":
            return (1.5 * cy - cx, float(bubble_order_idx), float(xmin))
        return (1.5 * cy - cx, 1_000_000.0 + float(ymin), -float(xmax))
    return (float(ymin), float(xmin), float(bubble_order_idx))


class LocalTranslationEngine(BaseTranslationEngine):
    """Composite local manga translation engine running Unified Hybrid DirectML inference."""

    def __init__(
        self,
        ocr_router: OCRRouter,
        translator_registry: TranslatorRegistry | None = None,
        translator: BaseTextTranslator | None = None,
        detector: Any = None,
        name: str = "local",
        default_ocr: str = "auto",
    ) -> None:
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

    async def _resolve_layout(
        self,
        request: TranslationRequest,
        image_bytes: bytes,
        width: int,
        height: int,
        bubbles: list[DetectedBubble] | None,
        layout: PageLayoutDetections | None,
    ) -> PageLayoutDetections:
        """Resolve page layout detections (skipping YOLO11 only for legacy reader_mode='text')."""
        if getattr(request, "reader_mode", "manga") == "text":
            return PageLayoutDetections(bubbles=[], panels=[], sfx_boxes=[], orphan_texts=[])
        if layout is not None:
            return layout
        if bubbles is not None:
            logger.debug(format_logfmt("GatewayDetectionsReceived", bubbles=len(bubbles)))
            return PageLayoutDetections(bubbles=bubbles, panels=[], sfx_boxes=[], orphan_texts=[])
        if self._detector is not None:
            async with track_stage("2/4", "Phát hiện bong bóng thoại & Layout (YOLO11s-seg)", logger) as stage_2:
                has_full_layout = callable(getattr(type(self._detector), "detect_full_layout", None))
                if has_full_layout:
                    detected_layout: PageLayoutDetections = await self._detector.detect_full_layout(
                        image_bytes, width, height
                    )
                else:
                    raw_bubbles: list[DetectedBubble] = await self._detector.detect(image_bytes, width, height)
                    detected_layout = PageLayoutDetections(
                        bubbles=raw_bubbles, panels=[], sfx_boxes=[], orphan_texts=[]
                    )
                stage_2.info = (
                    f"Tìm thấy {len(detected_layout.bubbles)} bong bóng, "
                    f"{len(detected_layout.sfx_boxes)} SFX mask"
                )
                return detected_layout
        return PageLayoutDetections(bubbles=[], panels=[], sfx_boxes=[], orphan_texts=[])

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
        layout: PageLayoutDetections | None = None,
    ) -> TranslationResponse:
        """Execute Unified Hybrid local translation pipeline (speech bubbles + residual prose)."""
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

        img_np = np.array(img)
        chapter_id = request.chapter_url or page_hash
        ocr_mode = (
            request.source_lang
            if request.source_lang and request.source_lang != "auto"
            else self._default_ocr
        )

        # 2. Layout Detection (YOLO11s-seg for curved bubble contours & SFX exclusion mask)
        effective_layout = await self._resolve_layout(
            request=request,
            image_bytes=image_bytes,
            width=width,
            height=height,
            bubbles=bubbles,
            layout=layout,
        )
        work_items = prepare_local_work_items(effective_layout.bubbles)

        # 3. Unified Hybrid OCR (Bucket A: curved bubbles, Bucket B: non-SFX prose/narration clusters)
        async with track_stage("3/4", f"HybridOCR (mode={ocr_mode})", logger) as stage_3:
            hybrid_result = await self._ocr_router.recognize_hybrid_page(
                image_np=img_np,
                work_items=work_items,
                sfx_boxes=effective_layout.sfx_boxes,
                image_width=width,
                image_height=height,
                chapter_id=chapter_id,
                requested_model=ocr_mode,
            )
            non_empty_bubbles = sum(1 for t in hybrid_result.bubble_texts if t.strip())
            non_empty_residuals = sum(1 for c in hybrid_result.residual_clusters if c.text.strip())
            stage_3.info = (
                f"adapter={hybrid_result.ocr_engine_used}, lang={hybrid_result.detected_source_lang}, "
                f"bubbles={non_empty_bubbles}/{len(work_items)}, residual={non_empty_residuals}"
            )

        # Build unified reading-ordered work queue combining bubbles and residual prose blocks
        combined_entries: list[
            tuple[str, int, BubbleWorkItem | None, ParagraphCluster | None, str]
        ] = []
        for idx, (item, raw_text) in enumerate(zip(work_items, hybrid_result.bubble_texts)):
            if raw_text.strip():
                combined_entries.append(("bubble", idx, item, None, raw_text))
        for r_idx, cluster in enumerate(hybrid_result.residual_clusters):
            if cluster.text.strip():
                combined_entries.append(("residual", r_idx, None, cluster, cluster.text))

        if not combined_entries:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(format_logfmt("EmptyOCROutput", action="SkipTranslate"))
            return TranslationResponse(
                page_hash=page_hash,
                engine_used=self._name,
                execution_time_ms=elapsed_ms,
                from_cache=False,
                blocks=[],
            )

        # Preserve exact YOLO panel/RTL sort when no residuals are interleaved; otherwise unify order
        has_both_or_residuals = bool(hybrid_result.residual_clusters)
        if has_both_or_residuals:
            use_rtl_order = bool(effective_layout.bubbles) or hybrid_result.page_dominant_vertical
            combined_entries.sort(
                key=lambda entry: _reading_order_key(
                    box_2d=(
                        entry[2].render_box
                        if entry[2] is not None
                        else (entry[3].box_2d if entry[3] is not None else (0, 0, 0, 0))
                    ),
                    kind=entry[0],
                    bubble_order_idx=entry[1],
                    use_rtl_manga_order=use_rtl_order,
                )
            )

        valid_raw_texts = [entry[4] for entry in combined_entries]
        effective_source_lang = (
            hybrid_result.detected_source_lang
            if hybrid_result.detected_source_lang != "auto"
            else (request.source_lang or "auto")
        )

        # 4. Single Batch Text Translation via TranslatorRegistry
        active_translator = self._translator_registry.get(request.translator)
        translate_kwargs: dict[str, Any] = {
            "source_lang": effective_source_lang,
            "target_lang": request.target_lang,
            "model": request.model,
        }
        if request.custom_prompt is not None:
            translate_kwargs["custom_prompt"] = request.custom_prompt

        async with track_stage(
            "4/4",
            f"BatchTranslate ({len(valid_raw_texts)} blocks [{effective_source_lang}->{request.target_lang}] via {active_translator.name})",
            logger,
        ) as stage_4:
            translated_texts = await active_translator.translate_batch(
                valid_raw_texts,
                **translate_kwargs,
            )
            stage_4.info = f"translated={len(translated_texts)}"

        # 5. Assemble TranslatedBlocks preserving smooth polygons on bubbles and flat boxes on prose
        bubble_work_items: list[BubbleWorkItem] = []
        bubble_raw_texts: list[str] = []
        bubble_translations: list[str] = []
        for entry, raw_text, trans_text in zip(combined_entries, valid_raw_texts, translated_texts):
            kind, _orig_idx, work_item, _res_cluster, _ = entry
            if kind == "bubble" and work_item is not None:
                bubble_work_items.append(work_item)
                bubble_raw_texts.append(raw_text)
                bubble_translations.append(trans_text)

        assembled_bubbles = (
            assemble_translated_blocks(
                bubbles=effective_layout.bubbles,
                translations=bubble_translations,
                raw_texts=bubble_raw_texts,
                work_items=bubble_work_items,
            )
            if bubble_work_items
            else []
        )
        # Key assembled bubbles uniquely by BubbleWorkItem identity while skipping empty translations
        assembled_by_wi_id: dict[int, TranslatedBlock] = {}
        b_cursor = 0
        for wi, t_txt in zip(bubble_work_items, bubble_translations):
            if not t_txt.strip():
                continue
            if b_cursor < len(assembled_bubbles):
                assembled_by_wi_id[id(wi)] = assembled_bubbles[b_cursor]
                b_cursor += 1

        blocks: list[TranslatedBlock] = []
        residual_seq = 0
        for entry, trans_text in zip(combined_entries, translated_texts):
            kind, _orig_idx, work_item, res_cluster, _ = entry
            if kind == "bubble" and work_item is not None:
                blk = assembled_by_wi_id.get(id(work_item))
                if blk is not None:
                    blocks.append(blk)
            elif kind == "residual" and res_cluster is not None and trans_text.strip():
                residual_seq += 1
                blocks.append(
                    TranslatedBlock(
                        id=f"text_p_{residual_seq}",
                        box=res_cluster.box_2d,
                        polygon=None,
                        parent_bubble_id=None,
                        parent_box=None,
                        source_text=res_cluster.text,
                        translated_text=trans_text,
                        direction=res_cluster.direction,
                        confidence=res_cluster.confidence,
                    )
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
        if not is_fallback and valid_raw_texts and request.target_lang == "vi" and effective_source_lang in ("en", "ja", "zh", "ko", "auto"):
            meaningful = [
                (r.strip(), t.strip())
                for r, t in zip(valid_raw_texts, translated_texts)
                if len(r.strip()) > 3
            ]
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
