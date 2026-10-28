"""Abstract protocol for text translation backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class TranslationBatch(list[str]):
    """List of translated strings with metadata indicating whether fallback was activated."""

    def __init__(self, iterable=(), is_fallback: bool = False) -> None:
        super().__init__(iterable)
        self.is_fallback = is_fallback


@runtime_checkable
class BaseTextTranslator(Protocol):
    """Protocol for text-only translation providers (e.g. GoogleFreeTranslator, LLMTextTranslator)."""

    @property
    def name(self) -> str:
        """Translator identifier (e.g. 'google-free', 'llm-text')."""
        ...

    async def is_available(self) -> bool:
        """Verify network reachability or credentials readiness."""
        ...

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str | None = None,
    ) -> list[str]:
        """Translate a batch of extracted dialogue sentences into the target language.

        Args:
            texts: List of dialogue strings extracted from speech bubbles.
            source_lang: Source language code (e.g. 'ja', 'en', 'zh', 'auto').
            target_lang: Target language code (e.g. 'vi').

        Returns:
            List of translated strings corresponding 1:1 with texts.
        """
        ...
