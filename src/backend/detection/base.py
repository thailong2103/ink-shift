"""Abstract protocol and dataclasses for speech bubble detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DetectedText:
    """Represents a localized line or block of text inside or outside a speech bubble.

    Coordinates follow the canonical normalized [0, 1000] integer bounding box:
    (ymin, xmin, ymax, xmax).
    """

    box_2d: tuple[int, int, int, int]
    confidence: float = 1.0


@dataclass(frozen=True)
class DetectedPanel:
    """Represents a manga panel bounding region on the page.

    Coordinates follow the canonical normalized [0, 1000] integer bounding box:
    (ymin, xmin, ymax, xmax).
    """

    box_2d: tuple[int, int, int, int]
    confidence: float = 1.0


@dataclass(frozen=True)
class DetectedBubble:
    """Represents a localized speech bubble within a manga page.

    Attributes:
        id: Unique identifier for this bubble.
        box_2d: Canonical normalized [0, 1000] integer bounding box: (ymin, xmin, ymax, xmax).
        polygon: List of 18-25 (x, y) vertices in [0.0, 100.0] relative percentage of the box.
        texts: List of independent child text blocks detected inside this bubble.
        panel_index: Assigned panel index for 2-tier reading order (-1 if unassigned).
        confidence: Detection confidence score in range [0.0, 1.0].
    """

    id: str
    box_2d: tuple[int, int, int, int]
    polygon: list[tuple[float, float]] = field(default_factory=list)
    texts: list[DetectedText] = field(default_factory=list)
    panel_index: int = -1
    confidence: float = 1.0


@runtime_checkable
class BaseBubbleDetector(Protocol):
    """Protocol for comic speech bubble detection models (YOLO11s-seg)."""

    @property
    def name(self) -> str:
        """Detector identifier (e.g. 'yolo11s-seg')."""
        ...

    async def is_available(self) -> bool:
        """Verify model weights and execution session readiness."""
        ...

    async def detect(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> list[DetectedBubble]:
        """Detect speech bubbles and return ordered bubbles with [0, 1000] boxes and polygons.

        Args:
            image_bytes: Raw binary bytes of the full page image.
            original_width: Original image width in physical pixels.
            original_height: Original image height in physical pixels.

        Returns:
            List of DetectedBubble instances with coordinates in [0, 1000] and relative polygons.
        """
        ...

    async def detect_layout(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> tuple[list[DetectedBubble], list[DetectedPanel]]:
        """Detect speech bubbles and panels simultaneously for reading order sorting.

        Args:
            image_bytes: Raw binary bytes of the full page image.
            original_width: Original image width in physical pixels.
            original_height: Original image height in physical pixels.

        Returns:
            Tuple of (bubbles, panels) with coordinates in [0, 1000].
        """
        ...
