"""Unit tests for local engine base protocols, dataclasses, and configuration."""

from __future__ import annotations

import pytest

from src.backend.config import Settings
from src.backend.detection.base import (
    BaseBubbleDetector,
    DetectedBubble,
    DetectedPanel,
)
from src.backend.engines.local.ocr.base import BaseOCREngine
from src.backend.engines.local.translator.base import BaseTextTranslator

# ---------------------------------------------------------------------------
# DetectedBubble Dataclass Tests
# ---------------------------------------------------------------------------


def test_detected_bubble_creation() -> None:
    """DetectedBubble should instantiate with expected fields and defaults."""
    bubble = DetectedBubble(
        id="b_1",
        box_2d=(100, 200, 300, 400),
        polygon=[(20.0, 10.0), (40.0, 10.0), (40.0, 30.0), (20.0, 30.0)],
        confidence=0.95,
    )
    assert bubble.id == "b_1"
    assert bubble.box_2d == (100, 200, 300, 400)
    assert len(bubble.polygon) == 4
    assert bubble.confidence == 0.95


def test_detected_bubble_defaults() -> None:
    """DetectedBubble should provide sensible defaults for optional fields."""
    bubble = DetectedBubble(id="b_def", box_2d=(0, 0, 500, 500))
    assert bubble.polygon == []
    assert bubble.confidence == 1.0
    assert bubble.texts == []
    assert bubble.panel_index == -1


def test_detected_bubble_frozen() -> None:
    """DetectedBubble must be immutable."""
    from dataclasses import FrozenInstanceError

    bubble = DetectedBubble(id="b_froz", box_2d=(0, 0, 100, 100))
    with pytest.raises(FrozenInstanceError):
        # Frozen dataclass mutation must raise FrozenInstanceError
        bubble.box_2d = 10, 10, 200, 200


# ---------------------------------------------------------------------------
# Protocol Conformance Tests
# ---------------------------------------------------------------------------


class MockDetector:
    """Compliant mock implementation of BaseBubbleDetector."""

    @property
    def name(self) -> str:
        return "mock-detector"

    async def is_available(self) -> bool:
        return True

    async def detect(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> list[DetectedBubble]:
        return [DetectedBubble(id="1", box_2d=(50, 50, 200, 200))]

    async def detect_layout(
        self,
        image_bytes: bytes,
        original_width: int,
        original_height: int,
    ) -> tuple[list[DetectedBubble], list[DetectedPanel]]:
        return [DetectedBubble(id="1", box_2d=(50, 50, 200, 200))], []


class IncompleteDetector:
    """Non-compliant detector missing detect method."""

    @property
    def name(self) -> str:
        return "incomplete"


class MockOCR:
    """Compliant mock implementation of BaseOCREngine."""

    @property
    def name(self) -> str:
        return "mock-ocr"

    async def is_available(self) -> bool:
        return True

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        return ["Konnichiwa"] * len(image_crops)


class IncompleteOCR:
    """Non-compliant OCR missing recognize_batch."""

    @property
    def name(self) -> str:
        return "incomplete"


class MockTranslator:
    """Compliant mock implementation of BaseTextTranslator."""

    @property
    def name(self) -> str:
        return "mock-translator"

    async def is_available(self) -> bool:
        return True

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str | None = None,
    ) -> list[str]:
        return [f"Xin chào: {t}" for t in texts]


class IncompleteTranslator:
    """Non-compliant translator missing translate_batch."""

    @property
    def name(self) -> str:
        return "incomplete"


def test_detector_protocol_conformance() -> None:
    """Detector classes must conform to BaseBubbleDetector protocol."""
    compliant = MockDetector()
    assert isinstance(compliant, BaseBubbleDetector)

    incomplete = IncompleteDetector()
    assert not isinstance(incomplete, BaseBubbleDetector)


def test_ocr_protocol_conformance() -> None:
    """OCR classes must conform to BaseOCREngine protocol."""
    compliant = MockOCR()
    assert isinstance(compliant, BaseOCREngine)

    incomplete = IncompleteOCR()
    assert not isinstance(incomplete, BaseOCREngine)


def test_translator_protocol_conformance() -> None:
    """Translator classes must conform to BaseTextTranslator protocol."""
    compliant = MockTranslator()
    assert isinstance(compliant, BaseTextTranslator)

    incomplete = IncompleteTranslator()
    assert not isinstance(incomplete, BaseTextTranslator)


# ---------------------------------------------------------------------------
# Configuration Settings Tests
# ---------------------------------------------------------------------------


def test_settings_local_defaults() -> None:
    """Settings should provide expected default configurations for local engine."""
    settings = Settings()
    assert settings.inkshift_local_model_dir == "./.cache/inkshift/models"
    assert settings.inkshift_local_default_ocr == "auto"
    assert settings.inkshift_local_execution_provider == "directml"
    assert settings.inkshift_local_default_translator == "google-free"
    assert settings.inkshift_local_detector_model_path == ""
    assert settings.inkshift_local_manga_ocr_model_path == ""


def test_settings_local_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should accept custom parameters and environment overrides."""
    monkeypatch.setenv("INKSHIFT_LOCAL_MODEL_DIR", "/custom/models")
    monkeypatch.setenv("INKSHIFT_LOCAL_DEFAULT_OCR", "rapidocr")
    monkeypatch.setenv("INKSHIFT_LOCAL_EXECUTION_PROVIDER", "cpu")
    monkeypatch.setenv("INKSHIFT_LOCAL_DEFAULT_TRANSLATOR", "llm-text")
    monkeypatch.setenv("INKSHIFT_LOCAL_DETECTOR_MODEL_PATH", "/models/detector.onnx")
    monkeypatch.setenv("INKSHIFT_LOCAL_MANGA_OCR_MODEL_PATH", "/models/manga.onnx")

    settings = Settings()
    assert settings.inkshift_local_model_dir == "/custom/models"
    assert settings.inkshift_local_default_ocr == "rapidocr"
    assert settings.inkshift_local_execution_provider == "cpu"
    assert settings.inkshift_local_default_translator == "llm-text"
    assert settings.inkshift_local_detector_model_path == "/models/detector.onnx"
    assert settings.inkshift_local_manga_ocr_model_path == "/models/manga.onnx"
