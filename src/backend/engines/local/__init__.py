"""Local On-Device Manga Translation Engine module."""

from src.backend.detection.base import (
    BaseBubbleDetector,
    DetectedBubble,
    DetectedPanel,
    DetectedText,
)
from src.backend.detection.yolo11_detector import YOLO11Detector
from src.backend.engines.local.engine import LocalTranslationEngine
from src.backend.engines.local.ocr.base import BaseOCREngine
from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.engines.local.translator.base import BaseTextTranslator
from src.backend.engines.local.translator.google_free import GoogleFreeTranslator
from src.backend.engines.local.translator.llm_text import LLMTextTranslator
from src.backend.engines.local.translator.registry import (
    TranslatorNotFoundError,
    TranslatorRegistry,
)

__all__ = [
    "BaseBubbleDetector",
    "BaseOCREngine",
    "BaseTextTranslator",
    "DetectedBubble",
    "DetectedPanel",
    "DetectedText",
    "GoogleFreeTranslator",
    "LLMTextTranslator",
    "LocalTranslationEngine",
    "OCRRouter",
    "RapidOCRAdapter",
    "TranslatorNotFoundError",
    "TranslatorRegistry",
    "YOLO11Detector",
]

