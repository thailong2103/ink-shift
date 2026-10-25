"""Protocol definition for cloud vision translation providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.backend.detection.base import DetectedBubble
from src.backend.schemas.contract import TranslatedBlock


@runtime_checkable
class CloudProvider(Protocol):
    """Protocol for concrete cloud vision providers (Gemini, xKiro/OpenAI)."""

    @property
    def name(self) -> str:
        """Provider identifier (e.g. 'gemini', 'openai')."""
        ...

    @property
    def default_model(self) -> str:
        """Default model identifier (e.g. 'gemini-2.0-flash', 'qwen/qwen2.5-vl-72b-instruct')."""
        ...

    async def is_available(self) -> bool:
        """Check whether provider credentials and endpoints are configured."""
        ...

    async def translate_page(
        self,
        image_base64: str,
        target_lang: str = "vi",
        model: str | None = None,
        bubbles: list[DetectedBubble] | None = None,
    ) -> list[TranslatedBlock]:
        """Execute vision translation using Set-of-Marks and return structured blocks."""
        ...
