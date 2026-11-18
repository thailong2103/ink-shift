"""Abstract protocol for optical character recognition (OCR) engines."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from src.backend.detection.assembler import BubbleWorkItem


@runtime_checkable
class BaseOCREngine(Protocol):
    """Protocol for manga OCR engines (e.g. MangaOCR, RapidOCR)."""

    @property
    def name(self) -> str:
        """OCR engine identifier (e.g. 'manga-ocr', 'rapidocr')."""
        ...

    async def is_available(self) -> bool:
        """Verify model weights and execution provider readiness."""
        ...

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        """Recognize and extract text strings from a batch of cropped speech bubbles.

        Args:
            image_crops: List of binary image bytes, each representing a single cropped bubble.

        Returns:
            List of transcribed text strings matching the order of image_crops.
        """
        ...


@runtime_checkable
class FullPageOCREngine(BaseOCREngine, Protocol):
    """Extended protocol for OCR engines supporting single-pass full-page recognition with spatial mapping."""

    async def recognize_full_page(
        self,
        image_np: np.ndarray[Any, Any],
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
    ) -> list[str]:
        """Recognize text across full page and map to work items using spatial intersection.

        Args:
            image_np: RGB numpy array representing the uncropped page.
            work_items: Sequence of BubbleWorkItem instances with canonical [0, 1000] crop_box.
            image_width: Original image width in pixels.
            image_height: Original image height in pixels.

        Returns:
            List of transcribed text strings matching the order of work_items.
        """
        ...

