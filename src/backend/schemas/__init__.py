"""Schema package exposing API contracts for InkShift."""

from src.backend.schemas.contract import (
    APIErrorDetail,
    APIErrorResponse,
    BoundingBox,
    Coordinate,
    HashString,
    TranslatedBlock,
    TranslationRequest,
    TranslationResponse,
)

__all__ = [
    "APIErrorDetail",
    "APIErrorResponse",
    "BoundingBox",
    "Coordinate",
    "HashString",
    "TranslatedBlock",
    "TranslationRequest",
    "TranslationResponse",
]
