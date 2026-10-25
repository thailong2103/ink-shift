"""Abstract Base Class for translation engines."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.detection.base import DetectedBubble
from src.backend.schemas.contract import TranslationRequest, TranslationResponse


class BaseTranslationEngine(abc.ABC):
    """Abstract interface for all translation providers (Cloud, Local, Mock)."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier of the translation engine."""

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """Check whether engine dependencies and credentials are ready."""

    @abc.abstractmethod
    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        """Process manga page image and return structured translated blocks."""


