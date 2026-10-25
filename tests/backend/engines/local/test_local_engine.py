"""Unit tests for LocalTranslationEngine composite pipeline."""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from PIL import Image

from src.backend.detection.base import DetectedBubble, DetectedText
from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.local.engine import LocalTranslationEngine
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.engines.local.translator.registry import TranslatorRegistry
from src.backend.schemas.contract import TranslationRequest

# ---------------------------------------------------------------------------
# Test Helpers & Stubs
# ---------------------------------------------------------------------------


def make_test_image_base64(width: int = 400, height: int = 600) -> str:
    """Create a test image in base64 format."""
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class StubDetector:
    """Stub bubble detector returning canned bounding boxes."""

    def __init__(self, bubbles: list[DetectedBubble] | None = None) -> None:
        self.bubbles = bubbles or []
        self.call_count = 0

    async def is_available(self) -> bool:
        return True

    async def detect(
        self, image_bytes: bytes, original_width: int, original_height: int
    ) -> list[DetectedBubble]:
        self.call_count += 1
        return self.bubbles


class StubOCR:
    """Stub OCR returning canned transcription strings."""

    def __init__(self, name: str, transcriptions: list[str] | None = None) -> None:
        self._name = name
        self.transcriptions = transcriptions or []
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return True

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        self.call_count += 1
        if self.transcriptions:
            return self.transcriptions[: len(image_crops)]
        return [f"text_{i}" for i in range(len(image_crops))]


class StubTranslator:
    """Stub translator returning canned translations."""

    def __init__(self, name: str = "google-free", prefix: str = "vi_") -> None:
        self._name = name
        self.prefix = prefix
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return True

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str | None = None,
    ) -> list[str]:
        self.call_count += 1
        return [f"{self.prefix}{t}" for t in texts]


# ---------------------------------------------------------------------------
# Composite Engine Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_engine_protocol_conformance() -> None:
    """LocalTranslationEngine must implement BaseTranslationEngine."""
    manga_ocr = StubOCR("manga-ocr")
    rapid_ocr = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr)

    engine = LocalTranslationEngine(
        detector=StubDetector(),
        ocr_router=router,
        translator=StubTranslator(),
        name="local",
    )

    assert isinstance(engine, BaseTranslationEngine)
    assert engine.name == "local"
    assert await engine.is_available() is True


@pytest.mark.asyncio
async def test_local_engine_full_pipeline() -> None:
    """LocalTranslationEngine coordinates detect -> crop -> OCR -> translate -> TranslationResponse."""
    bubbles = [
        DetectedBubble(
            id="1",
            box_2d=(100, 150, 300, 350),
            polygon=[(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)],
            confidence=0.95,
        ),
        DetectedBubble(
            id="2",
            box_2d=(500, 600, 700, 800),
            confidence=0.92,
        ),
    ]
    detector = StubDetector(bubbles)

    manga_ocr = StubOCR("manga-ocr", transcriptions=["こんにちは", "逃げろ！"])
    rapid_ocr = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr)

    translator = StubTranslator(prefix="dịch_")

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
        default_ocr="manga-ocr",
    )

    req = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="ja",
        target_lang="vi",
        engine="local",
    )

    resp = await engine.translate(req)

    assert resp.success is True
    assert resp.engine_used == "local"
    assert resp.from_cache is False
    assert resp.execution_time_ms >= 0
    assert len(resp.blocks) == 2

    block0 = resp.blocks[0]
    assert block0.id == "blk_0"
    assert block0.box == (100, 150, 300, 350)
    assert block0.parent_box is None
    assert block0.polygon == [(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)]
    assert block0.source_text == "こんにちは"
    assert block0.translated_text == "dịch_こんにちは"
    assert block0.confidence == 0.95

    block1 = resp.blocks[1]
    assert block1.id == "blk_1"
    assert block1.box == (500, 600, 700, 800)
    assert block1.parent_box is None
    assert block1.source_text == "逃げろ！"
    assert block1.translated_text == "dịch_逃げろ！"
    assert block1.confidence == 0.92


@pytest.mark.asyncio
async def test_local_engine_merged_bubble_child_texts() -> None:
    """Connected/merged bubble with multiple child texts emits linked TranslatedBlock records."""
    child_text1 = DetectedText(box_2d=(110, 160, 190, 340), confidence=0.96)
    child_text2 = DetectedText(box_2d=(210, 160, 290, 340), confidence=0.94)

    merged_bubble = DetectedBubble(
        id="1",
        box_2d=(100, 150, 300, 350),
        polygon=[(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)],
        texts=[child_text1, child_text2],
        confidence=0.98,
    )
    detector = StubDetector([merged_bubble])

    manga_ocr = StubOCR("manga-ocr", transcriptions=["Line 1", "Line 2"])
    rapid_ocr = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr)
    translator = StubTranslator(prefix="vi_")

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
        default_ocr="manga-ocr",
    )

    req = TranslationRequest(image=make_test_image_base64(), engine="local")
    resp = await engine.translate(req)

    # Must emit 2 blocks corresponding to child texts
    assert len(resp.blocks) == 2
    assert resp.blocks[0].id == "blk_0_1"
    assert resp.blocks[0].box == (110, 160, 197, 340)
    assert resp.blocks[0].parent_bubble_id == "1"
    assert resp.blocks[0].parent_box == (100, 150, 300, 350)
    assert resp.blocks[0].polygon == [(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)]
    assert resp.blocks[0].translated_text == "vi_Line 1"

    assert resp.blocks[1].id == "blk_1_2"
    assert resp.blocks[1].box == (203, 160, 290, 340)
    assert resp.blocks[1].parent_bubble_id == "1"
    assert resp.blocks[1].parent_box == (100, 150, 300, 350)
    assert resp.blocks[1].polygon == [(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)]
    assert resp.blocks[1].translated_text == "vi_Line 2"


@pytest.mark.asyncio
async def test_local_engine_no_bubbles_detected() -> None:
    """When no bubbles are detected, engine returns empty blocks cleanly."""
    detector = StubDetector([])
    manga_ocr = StubOCR("manga-ocr")
    rapid_ocr = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr)
    translator = StubTranslator()

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
    )

    req = TranslationRequest(image=make_test_image_base64(), engine="local")
    resp = await engine.translate(req)

    assert resp.success is True
    assert resp.blocks == []
    assert manga_ocr.call_count == 0
    assert translator.call_count == 0


@pytest.mark.asyncio
async def test_local_engine_corrupt_image_raises_value_error() -> None:
    """Corrupt or non-base64 image payload raises ValueError."""
    engine = LocalTranslationEngine(
        detector=StubDetector(),
        ocr_router=OCRRouter(StubOCR("manga-ocr"), StubOCR("rapidocr")),
        translator=StubTranslator(),
    )

    req = TranslationRequest(image="not_base64_data", engine="local")
    with pytest.raises(ValueError):
        await engine.translate(req)


@pytest.mark.asyncio
async def test_local_engine_named_variants() -> None:
    """LocalTranslationEngine variants ('local-manga', 'local-rapid') configure specific defaults."""
    manga_ocr = StubOCR("manga-ocr")
    rapid_ocr = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr)

    engine_manga = LocalTranslationEngine(
        detector=StubDetector([DetectedBubble(id="1", box_2d=(10, 10, 50, 50), confidence=0.9)]),
        ocr_router=router,
        translator=StubTranslator(),
        name="local-manga",
        default_ocr="manga-ocr",
    )

    req = TranslationRequest(image=make_test_image_base64(), engine="local")
    resp = await engine_manga.translate(req)
    assert resp.engine_used == "local-manga"
    assert manga_ocr.call_count == 1
    assert rapid_ocr.call_count == 0


@pytest.mark.asyncio
async def test_local_engine_single_child_polygon_safe_expansion() -> None:
    """Single child text in spiky polygon must expand only within safe core, setting parent_box."""
    # Outer bubble box: (100, 100, 500, 500) (size 400x400)
    # Spiky polygon with valleys at 30% and tips at 10% / 90%
    star_polygon = [
        (50.0, 10.0),   # Top tip
        (60.0, 35.0),   # Valley
        (90.0, 50.0),   # Right tip
        (60.0, 65.0),   # Valley
        (50.0, 90.0),   # Bottom tip
        (40.0, 65.0),   # Valley
        (10.0, 50.0),   # Left tip
        (40.0, 35.0),   # Valley
    ]
    # Center text: (280, 280, 320, 320) (40x40 at center 300, 300)
    child_text = DetectedText(box_2d=(280, 280, 320, 320), confidence=0.95)
    bubble = DetectedBubble(
        id="star_1",
        box_2d=(100, 100, 500, 500),
        polygon=star_polygon,
        texts=[child_text],
        confidence=0.98,
    )

    detector = StubDetector([bubble])
    router = OCRRouter(manga_ocr=StubOCR("manga-ocr"), rapid_ocr=StubOCR("rapidocr", ["GLORY"]))
    translator = StubTranslator(prefix="dịch_")

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
        default_ocr="rapidocr",
    )

    req = TranslationRequest(image=make_test_image_base64(), engine="local")
    resp = await engine.translate(req)

    assert len(resp.blocks) == 1
    block = resp.blocks[0]
    assert block.parent_box == (100, 100, 500, 500)
    assert block.parent_bubble_id == "star_1"
    # Block box must be expanded beyond initial 40x40 text, BUT strictly inside valleys (< 400x400 parent)
    b_ymin, b_xmin, b_ymax, b_xmax = block.box
    b_h = b_ymax - b_ymin
    b_w = b_xmax - b_xmin
    assert b_h > 40 and b_w > 40
    assert b_h < 400 and b_w < 400
    assert block.polygon == star_polygon


@pytest.mark.asyncio
async def test_local_engine_source_lang_dispatch() -> None:
    """Verify request.source_lang directly routes OCR adapter and chapter_url caches."""
    bubble = DetectedBubble(
        id="b_1",
        box_2d=(100, 100, 300, 300),
        confidence=0.99,
    )
    detector = StubDetector([bubble])

    manga_stub = StubOCR("manga-ocr", ["こんにちは"])
    rapid_stub = StubOCR("rapidocr", ["Hello World"])

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub, default_model="rapidocr")
    translator = StubTranslator()

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
        default_ocr="rapidocr",
    )

    # 1. Explicit source_lang="ja" overrides default_ocr="rapidocr"
    req_ja = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="ja",
        chapter_url="https://manga.org/series/chapter-1",
    )
    resp_ja = await engine.translate(req_ja)
    assert manga_stub.call_count == 1
    assert rapid_stub.call_count == 0
    assert resp_ja.blocks[0].source_text == "こんにちは"

    # 2. Explicit source_lang="en" routes to rapidocr
    req_en = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="en",
        chapter_url="https://comic.org/series/issue-1",
    )
    resp_en = await engine.translate(req_en)
    assert rapid_stub.call_count == 1
    assert resp_en.blocks[0].source_text == "Hello World"


@pytest.mark.asyncio
async def test_local_engine_injected_bubbles_skips_detection() -> None:
    """When pre-detected bubbles are provided by the gateway, internal detection is bypassed."""
    bubble = DetectedBubble(
        id="injected_1",
        box_2d=(100, 100, 300, 300),
        confidence=0.99,
    )
    detector = StubDetector([bubble])

    manga_stub = StubOCR("manga-ocr", ["テスト"])
    rapid_stub = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub, default_model="manga-ocr")
    translator = StubTranslator(prefix="vi_")

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
    )

    req = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="ja",
        engine="local",
    )

    # Pass bubbles explicitly
    resp = await engine.translate(req, bubbles=[bubble])

    # Detector was NEVER called!
    assert detector.call_count == 0
    assert len(resp.blocks) == 1
    assert resp.blocks[0].translated_text == "vi_テスト"


@pytest.mark.asyncio
async def test_local_engine_translator_registry_routing() -> None:
    """LocalTranslationEngine should use request.translator to route text translation."""
    bubble = DetectedBubble(
        id="b_1",
        box_2d=(100, 100, 300, 300),
        confidence=0.99,
    )
    manga_stub = StubOCR("manga-ocr", ["テキスト"])
    rapid_stub = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub, default_model="manga-ocr")

    google_stub = StubTranslator(name="google-free", prefix="google_")
    llm_stub = StubTranslator(name="llm-text", prefix="llm_")

    registry = TranslatorRegistry(default_translator_name="google-free")
    registry.register("google-free", google_stub)
    registry.register("llm-text", llm_stub)

    engine = LocalTranslationEngine(
        ocr_router=router,
        translator_registry=registry,
        name="local",
    )

    req_default = TranslationRequest(image=make_test_image_base64(), source_lang="ja", engine="local")
    resp_default = await engine.translate(req_default, bubbles=[bubble])
    assert google_stub.call_count == 1
    assert llm_stub.call_count == 0
    assert resp_default.blocks[0].translated_text == "google_テキスト"

    req_llm = TranslationRequest(image=make_test_image_base64(), source_lang="ja", engine="local", translator="llm-text")
    resp_llm = await engine.translate(req_llm, bubbles=[bubble])
    assert llm_stub.call_count == 1
    assert resp_llm.blocks[0].translated_text == "llm_テキスト"


@pytest.mark.asyncio
async def test_local_engine_filters_empty_ocr_transcriptions() -> None:
    """LocalTranslationEngine filters out empty or whitespace OCR results before translation."""
    b1 = DetectedBubble(id="b1", box_2d=(100, 100, 200, 200), confidence=0.9)
    b2 = DetectedBubble(id="b2", box_2d=(300, 300, 400, 400), confidence=0.9)
    b3 = DetectedBubble(id="b3", box_2d=(500, 500, 600, 600), confidence=0.9)

    manga_stub = StubOCR("manga-ocr", ["Valid dialogue", "", "   \t\n  "])
    rapid_stub = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub, default_model="manga-ocr")

    translator = StubTranslator(prefix="dịch_")
    engine = LocalTranslationEngine(
        ocr_router=router,
        translator=translator,
        name="local",
    )

    req = TranslationRequest(image=make_test_image_base64(), source_lang="ja", engine="local")
    resp = await engine.translate(req, bubbles=[b1, b2, b3])

    # Translator only receives the 1 valid non-empty string
    assert translator.call_count == 1
    assert len(resp.blocks) == 1
    assert resp.blocks[0].id == "blk_0"
    assert resp.blocks[0].translated_text == "dịch_Valid dialogue"


@pytest.mark.asyncio
async def test_local_engine_all_empty_ocr_early_returns_clean_response() -> None:
    """When all OCR crops yield empty or whitespace text, returns empty blocks without calling translator."""
    b1 = DetectedBubble(id="b1", box_2d=(100, 100, 200, 200), confidence=0.9)
    b2 = DetectedBubble(id="b2", box_2d=(300, 300, 400, 400), confidence=0.9)

    manga_stub = StubOCR("manga-ocr", ["", "   "])
    rapid_stub = StubOCR("rapidocr")
    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub, default_model="manga-ocr")

    translator = StubTranslator(prefix="dịch_")
    engine = LocalTranslationEngine(
        ocr_router=router,
        translator=translator,
        name="local",
    )

    req = TranslationRequest(image=make_test_image_base64(), source_lang="ja", engine="local")
    resp = await engine.translate(req, bubbles=[b1, b2])

    assert translator.call_count == 0
    assert resp.blocks == []
    assert resp.page_hash is not None


@pytest.mark.asyncio
async def test_local_engine_with_llm_gemini_and_qwen_selection() -> None:
    """LocalTranslationEngine accurately routes batch translation to selected LLM translator."""
    manga_ocr = StubOCR("manga-ocr", transcriptions=["こんにちは"])
    rapid_ocr = StubOCR("rapidocr", transcriptions=["hello"])
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr, default_model="manga-ocr")

    reg = TranslatorRegistry(default_translator_name="google-free")
    t_google = StubTranslator(name="google-free", prefix="google_")
    t_gemini = StubTranslator(name="llm-gemini", prefix="gemini_")
    t_qwen = StubTranslator(name="llm-qwen", prefix="qwen_")

    reg.register("google-free", t_google)
    reg.register("llm-gemini", t_gemini)
    reg.register("llm-qwen", t_qwen)

    engine = LocalTranslationEngine(
        ocr_router=router,
        translator_registry=reg,
        name="local",
    )

    bubble = DetectedBubble(
        id="bubble_0",
        box_2d=(100, 100, 300, 300),
        confidence=0.9,
        texts=[DetectedText(box_2d=(120, 120, 280, 280), confidence=0.9)],
    )

    # 1. Translate with llm-gemini
    req_gemini = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="ja",
        engine="local",
        translator="llm-gemini",
    )
    resp_gemini = await engine.translate(req_gemini, bubbles=[bubble])
    assert len(resp_gemini.blocks) == 1
    assert resp_gemini.blocks[0].translated_text.startswith("gemini_")
    assert t_gemini.call_count == 1
    assert t_qwen.call_count == 0

    # 2. Translate with llm-qwen
    req_qwen = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="ja",
        engine="local",
        translator="llm-qwen",
    )
    resp_qwen = await engine.translate(req_qwen, bubbles=[bubble])
    assert len(resp_qwen.blocks) == 1
    assert resp_qwen.blocks[0].translated_text.startswith("qwen_")
    assert t_gemini.call_count == 1
    assert t_qwen.call_count == 1


class StubFullPageOCR(StubOCR):
    """Stub OCR supporting full-page single pass recognition."""

    def __init__(self, name: str, transcriptions: list[str] | None = None) -> None:
        super().__init__(name, transcriptions)
        self.full_page_calls = 0

    @property
    def supports_full_page(self) -> bool:
        return True

    async def recognize_full_page(
        self,
        image_np: Any,
        work_items: Any,
        image_width: int,
        image_height: int,
    ) -> list[str]:
        self.full_page_calls += 1
        return self.transcriptions[: len(work_items)]


@pytest.mark.asyncio
async def test_local_engine_rapidocr_full_page_bypass_cropping() -> None:
    """LocalTranslationEngine with rapidocr should use single-pass full-page OCR without crops."""
    manga_ocr = StubOCR("manga-ocr", ["Japanese text"])
    rapid_ocr = StubFullPageOCR("rapidocr", ["Full-Page English"])
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr, default_model="rapidocr")

    translator = StubTranslator("mock-trans", prefix="tr_")
    reg = TranslatorRegistry(default_translator_name="mock-trans")
    reg.register("mock-trans", translator)

    engine = LocalTranslationEngine(
        ocr_router=router,
        translator_registry=reg,
        name="local",
        default_ocr="rapidocr",
    )

    bubble = DetectedBubble(id="b_fp", box_2d=(100, 100, 300, 300))
    req = TranslationRequest(
        image=make_test_image_base64(),
        source_lang="en",
        engine="local",
    )

    resp = await engine.translate(req, bubbles=[bubble])

    assert len(resp.blocks) == 1
    assert resp.blocks[0].source_text == "Full-Page English"
    assert resp.blocks[0].translated_text == "tr_Full-Page English"
    # RapidOCR full-page was called, MangaOCR was never touched!
    assert rapid_ocr.full_page_calls == 1
    assert rapid_ocr.call_count == 0  # No crop-based calls!
    assert manga_ocr.call_count == 0





