"""Deterministic mock translation engine for tests and contract verification."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.detection.base import DetectedBubble
from src.backend.engines.base import BaseTranslationEngine
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.contract import (
    TranslatedBlock,
    TranslationRequest,
    TranslationResponse,
)

logger = get_logger("mock_engine")


class MockTranslationEngine(BaseTranslationEngine):
    """Deterministic mock provider returning contract-compliant manga translations."""

    @property
    def name(self) -> str:
        return "mock"

    async def is_available(self) -> bool:
        return True

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        """Generate deterministic translated blocks within [0, 1000] coordinate space."""
        if request.image_hash:
            page_hash = request.image_hash
        else:
            page_hash = hashlib.sha256(request.image.encode("utf-8")).hexdigest()

        logger.debug(
            format_logfmt(
                "MockTranslateExecuted",
                page_hash=page_hash[:16],
                target_lang=request.target_lang,
            )
        )

        blocks: list[TranslatedBlock] = [
            TranslatedBlock(
                id="blk_mock_01",
                box=(120, 680, 320, 880),
                source_text="何をしているんだ？",
                translated_text="Cậu đang làm cái gì thế?",
                direction="vertical",
                confidence=0.98,
            ),
            TranslatedBlock(
                id="blk_mock_02",
                box=(410, 340, 620, 560),
                source_text="別に…何でもないよ。",
                translated_text="Không có gì... Không có chuyện gì đâu.",
                direction="vertical",
                confidence=0.95,
            ),
            TranslatedBlock(
                id="blk_mock_03",
                box=(700, 120, 880, 300),
                source_text="本当か？",
                translated_text="Thật không đấy?",
                direction="vertical",
                confidence=0.92,
            ),
        ]

        return TranslationResponse(
            page_hash=page_hash,
            engine_used=self.name,
            execution_time_ms=15,
            from_cache=False,
            blocks=blocks,
        )
