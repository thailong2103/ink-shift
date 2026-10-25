"""Unit tests for swappable OCR adapters (RapidOCR and MangaOCR)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from src.backend.detection.assembler import BubbleWorkItem
from src.backend.detection.base import DetectedBubble
from src.backend.engines.local.ocr.base import BaseOCREngine, FullPageOCREngine
from src.backend.engines.local.ocr.manga_ocr import MangaOCRAdapter
from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter

# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_dummy_crop_bytes(color: str = "white", size: tuple[int, int] = (200, 100)) -> bytes:
    """Create in-memory binary image crop bytes for OCR testing."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# RapidOCRAdapter Tests
# ---------------------------------------------------------------------------


class MockRapidOCREngine:
    """Mock engine simulating rapidocr-onnxruntime output structure."""

    def __init__(self, mock_results: list[Any]) -> None:
        self.mock_results = mock_results
        self.call_count = 0

    def __call__(self, img_np: Any) -> tuple[list[Any], float]:
        self.call_count += 1
        # Returns (result_list, elapse_time)
        return self.mock_results, 0.025


@pytest.mark.asyncio
async def test_rapid_ocr_protocol_conformance() -> None:
    """RapidOCRAdapter must implement BaseOCREngine protocol."""
    adapter = RapidOCRAdapter(rapidocr_engine=MockRapidOCREngine([]))
    assert isinstance(adapter, BaseOCREngine)
    assert adapter.name == "rapidocr"
    assert await adapter.is_available() is True


@pytest.mark.asyncio
async def test_rapid_ocr_recognize_batch() -> None:
    """RapidOCRAdapter should recognize, sort, and assemble multi-line comic speech bubbles."""
    # RapidOCR output format: [[box, text, confidence], ...]
    # Line 2 appears at top y=10.0, Line 1 appears at y=60.0
    mock_data = [
        [[[0, 60], [100, 60], [100, 90], [0, 90]], "HERE?!", 0.98],
        [[[0, 10], [100, 10], [100, 40], [0, 40]], "WHAT ARE YOU DOING", 0.99],
    ]
    mock_engine = MockRapidOCREngine(mock_data)
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    crop = make_dummy_crop_bytes()
    results = await adapter.recognize_batch([crop])

    assert len(results) == 1
    # Must be sorted vertically (top line first) and assembled
    assert results[0] == "WHAT ARE YOU DOING HERE?!"
    assert mock_engine.call_count == 1


@pytest.mark.asyncio
async def test_rapid_ocr_empty_and_corrupt_crops() -> None:
    """RapidOCRAdapter should handle empty or corrupt image crops gracefully."""
    mock_engine = MockRapidOCREngine([])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    results = await adapter.recognize_batch([b"", b"not_an_image", make_dummy_crop_bytes()])
    assert results == ["", "", ""]


@pytest.mark.asyncio
async def test_rapid_ocr_empty_batch() -> None:
    """Empty batch should immediately return empty list without engine calls."""
    mock_engine = MockRapidOCREngine([])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)
    assert await adapter.recognize_batch([]) == []
    assert mock_engine.call_count == 0


@pytest.mark.asyncio
async def test_rapid_ocr_engine_initialization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing dependency must raise RuntimeError during inference."""
    adapter = RapidOCRAdapter(rapidocr_engine=None)

    def failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "rapidocr_onnxruntime":
            raise ImportError("Simulated missing package")
        import importlib
        return importlib.__import__(name, *args, **kwargs)

    import importlib
    monkeypatch.setattr(importlib, "import_module", failing_import)

    with pytest.raises(RuntimeError) as exc_info:
        await adapter.recognize_batch([make_dummy_crop_bytes()])
    assert "Failed to initialize RapidOCR" in str(exc_info.value)


# ---------------------------------------------------------------------------
# MangaOCRAdapter Tests
# ---------------------------------------------------------------------------


class MockMangaOCREngine:
    """Mock engine simulating MangaOcr instance."""

    def __init__(self, transcription: str = "何をしているの？") -> None:
        self.transcription = transcription
        self.call_count = 0

    def __call__(self, img: Image.Image) -> str:
        self.call_count += 1
        return self.transcription


@pytest.mark.asyncio
async def test_manga_ocr_protocol_conformance() -> None:
    """MangaOCRAdapter must implement BaseOCREngine protocol."""
    adapter = MangaOCRAdapter(manga_ocr_engine=MockMangaOCREngine())
    assert isinstance(adapter, BaseOCREngine)
    assert adapter.name == "manga-ocr"
    assert await adapter.is_available() is True


@pytest.mark.asyncio
async def test_manga_ocr_recognize_batch() -> None:
    """MangaOCRAdapter should transcribe Japanese text and clean spaces."""
    mock_engine = MockMangaOCREngine("私 は   逃 げ ま す ！")
    adapter = MangaOCRAdapter(manga_ocr_engine=mock_engine)

    crop1 = make_dummy_crop_bytes()
    crop2 = make_dummy_crop_bytes()
    results = await adapter.recognize_batch([crop1, crop2])

    assert len(results) == 2
    # Cleans spaces between CJK characters
    assert results[0] == "私は逃げます！"
    assert results[1] == "私は逃げます！"
    assert mock_engine.call_count == 2


@pytest.mark.asyncio
async def test_manga_ocr_empty_and_corrupt_crops() -> None:
    """MangaOCRAdapter should handle empty or corrupt image crops without crashing."""
    mock_engine = MockMangaOCREngine("こんにちは")
    adapter = MangaOCRAdapter(manga_ocr_engine=mock_engine)

    results = await adapter.recognize_batch([b"", b"not_an_image"])
    assert results == ["", ""]
    assert mock_engine.call_count == 0


@pytest.mark.asyncio
async def test_manga_ocr_empty_batch() -> None:
    """Empty batch should immediately return empty list without engine calls."""
    mock_engine = MockMangaOCREngine()
    adapter = MangaOCRAdapter(manga_ocr_engine=mock_engine)
    assert await adapter.recognize_batch([]) == []
    assert mock_engine.call_count == 0


@pytest.mark.asyncio
async def test_manga_ocr_missing_model_error() -> None:
    """Missing model weights and package must raise RuntimeError."""
    adapter = MangaOCRAdapter(manga_ocr_engine=None, model_path="/non_existent/manga.onnx")

    with pytest.raises(RuntimeError) as exc_info:
        await adapter.recognize_batch([make_dummy_crop_bytes()])
    assert "Failed to initialize MangaOCR" in str(exc_info.value)


# ---------------------------------------------------------------------------
# FullPageOCREngine & Spatial Mapping Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_ocr_full_page_protocol_conformance() -> None:
    """RapidOCRAdapter must implement FullPageOCREngine protocol."""
    adapter = RapidOCRAdapter(rapidocr_engine=MockRapidOCREngine([]))
    assert isinstance(adapter, FullPageOCREngine)
    assert adapter.supports_full_page is True
    assert adapter.name == "rapidocr"


@pytest.mark.asyncio
async def test_rapid_ocr_recognize_full_page_spatial_mapping() -> None:
    """RapidOCRAdapter should map detected lines into containing bubbles and sort vertically."""
    # Canonical space: [0, 1000]
    b1 = DetectedBubble(id="b1", box_2d=(100, 100, 300, 400))
    b2 = DetectedBubble(id="b2", box_2d=(500, 500, 800, 900))
    b3 = DetectedBubble(id="b3", box_2d=(850, 100, 950, 300))

    item1 = BubbleWorkItem(
        crop_box=(100, 100, 300, 400),
        render_box=(100, 100, 300, 400),
        parent_bubble=b1,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )
    item2 = BubbleWorkItem(
        crop_box=(500, 500, 800, 900),
        render_box=(500, 500, 800, 900),
        parent_bubble=b2,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )
    item3 = BubbleWorkItem(
        crop_box=(850, 100, 950, 300),
        render_box=(850, 100, 950, 300),
        parent_bubble=b3,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )

    # Mock OCR output on 1000x1000 image:
    # Item for Bubble 1 - Line 2 (y=220)
    # Item for Bubble 1 - Line 1 (y=150) -> should be sorted before Line 2
    # Item for Bubble 2 - Line 1 (y=600)
    # Outside item (y=50, x=50) -> outside all bubbles, should be ignored
    mock_results = [
        [[[150.0, 220.0], [350.0, 220.0], [350.0, 250.0], [150.0, 250.0]], "WORLD!", 0.95],
        [[[150.0, 150.0], [350.0, 150.0], [350.0, 180.0], [150.0, 180.0]], "HELLO", 0.98],
        [[[550.0, 600.0], [750.0, 600.0], [750.0, 640.0], [550.0, 640.0]], "SECOND BUBBLE", 0.92],
        [[[10.0, 50.0], [80.0, 50.0], [80.0, 70.0], [10.0, 70.0]], "OUTSIDE SFX", 0.70],
    ]

    mock_engine = MockRapidOCREngine(mock_results)
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    img_dummy = Image.new("RGB", (1000, 1000), color="white")
    results = await adapter.recognize_full_page(
        image_np=img_dummy,
        work_items=[item1, item2, item3],
        image_width=1000,
        image_height=1000,
    )

    assert len(results) == 3
    # Bubble 1: sorted top-to-bottom
    assert results[0] == "HELLO WORLD!"
    # Bubble 2: single line
    assert results[1] == "SECOND BUBBLE"
    # Bubble 3: no text
    assert results[2] == ""
    # Single call on full image!
    assert mock_engine.call_count == 1


@pytest.mark.asyncio
async def test_rapid_ocr_recognize_full_page_empty_work_items() -> None:
    """recognize_full_page should return empty list when no work items provided."""
    mock_engine = MockRapidOCREngine([])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)
    results = await adapter.recognize_full_page(
        image_np=Image.new("RGB", (100, 100)),
        work_items=[],
        image_width=100,
        image_height=100,
    )
    assert results == []
    assert mock_engine.call_count == 0

