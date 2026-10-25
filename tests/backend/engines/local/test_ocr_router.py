"""Unit tests for OCRRouter (Language Auto-Probe, Unicode Classifier, and Chapter Cache)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from src.backend.detection.assembler import BubbleWorkItem
from src.backend.engines.local.ocr.router import OCRRouter

# ---------------------------------------------------------------------------
# Test Helpers & Stubs
# ---------------------------------------------------------------------------


def make_dummy_crop_bytes(color: str = "white", size: tuple[int, int] = (100, 50)) -> bytes:
    """Create in-memory PNG bytes for testing."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class StubOCREngine:
    """Stub OCR engine tracking calls and returning canned responses."""

    def __init__(self, name: str, canned_text: str = "") -> None:
        self._name = name
        self.canned_text = canned_text
        self.call_count = 0
        self.last_crops: list[bytes] = []

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return True

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        self.call_count += 1
        self.last_crops = image_crops
        return [self.canned_text for _ in image_crops]


# ---------------------------------------------------------------------------
# Script Classification Tests
# ---------------------------------------------------------------------------


def test_classify_text_script_japanese() -> None:
    """Text containing Hiragana or Katakana should resolve to 'manga-ocr'."""
    router = OCRRouter(
        manga_ocr=StubOCREngine("manga-ocr"),
        rapid_ocr=StubOCREngine("rapidocr"),
    )

    # Pure Hiragana
    assert router.classify_text_script("こんにちは") == "manga-ocr"
    assert router.classify_text_script("これはペンです") == "manga-ocr"

    # Katakana / Onomatopoeia
    assert router.classify_text_script("ドカン！") == "manga-ocr"
    assert router.classify_text_script("ドキドキ") == "manga-ocr"

    # Mixed Kanji + Hiragana / Katakana
    assert router.classify_text_script("何をしているの？") == "manga-ocr"
    assert router.classify_text_script("私のお金") == "manga-ocr"


def test_classify_text_script_latin() -> None:
    """Text with Latin characters should resolve to 'rapidocr'."""
    router = OCRRouter(
        manga_ocr=StubOCREngine("manga-ocr"),
        rapid_ocr=StubOCREngine("rapidocr"),
    )

    assert router.classify_text_script("What are you doing?!") == "rapidocr"
    assert router.classify_text_script("HELLO WORLD") == "rapidocr"
    assert router.classify_text_script("Chapter 1: The Beginning") == "rapidocr"


def test_classify_text_script_chinese() -> None:
    """Chinese text (Hanzi without Kana) should resolve to 'rapidocr'."""
    router = OCRRouter(
        manga_ocr=StubOCREngine("manga-ocr"),
        rapid_ocr=StubOCREngine("rapidocr"),
    )

    assert router.classify_text_script("你好世界") == "rapidocr"
    assert router.classify_text_script("这是什么东西") == "rapidocr"


def test_classify_text_script_korean() -> None:
    """Korean text (Hangul syllables/jamo) should resolve to 'rapidocr'."""
    router = OCRRouter(
        manga_ocr=StubOCREngine("manga-ocr"),
        rapid_ocr=StubOCREngine("rapidocr"),
    )

    assert router.classify_text_script("안녕하세요") == "rapidocr"
    assert router.classify_text_script("대박! 진짜?") == "rapidocr"
    assert router.classify_text_script("웹툰 만화") == "rapidocr"


def test_classify_text_script_fallback() -> None:
    """Empty, whitespace, or punctuation-only text should fallback gracefully."""
    router = OCRRouter(
        manga_ocr=StubOCREngine("manga-ocr"),
        rapid_ocr=StubOCREngine("rapidocr"),
        fallback_model="manga-ocr",
    )

    assert router.classify_text_script("") == "manga-ocr"
    assert router.classify_text_script("   \n\t") == "manga-ocr"
    assert router.classify_text_script("...!?---") == "manga-ocr"


# ---------------------------------------------------------------------------
# Manual Override Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_override_bypasses_probe() -> None:
    """Explicit requested_model must immediately return requested adapter without calling probe."""
    manga_stub = StubOCREngine("manga-ocr")
    rapid_stub = StubOCREngine("rapidocr")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)

    # 1. Override: manga-ocr
    adapter = await router.resolve_engine(
        requested_model="manga-ocr",
        sample_crops=[make_dummy_crop_bytes()],
    )
    assert adapter.name == "manga-ocr"
    assert rapid_stub.call_count == 0  # RapidOCR probe was bypassed!

    # 2. Override: rapidocr
    adapter = await router.resolve_engine(
        requested_model="rapidocr",
        sample_crops=[make_dummy_crop_bytes()],
    )
    assert adapter.name == "rapidocr"
    assert rapid_stub.call_count == 0  # RapidOCR probe was bypassed!


@pytest.mark.asyncio
async def test_manual_override_language_codes() -> None:
    """Explicit language codes ('ja', 'en', 'ko', 'zh') route directly without probe."""
    manga_stub = StubOCREngine("manga-ocr")
    rapid_stub = StubOCREngine("rapidocr")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)

    # 'ja' -> manga-ocr
    ad_ja = await router.resolve_engine(requested_model="ja", sample_crops=[make_dummy_crop_bytes()])
    assert ad_ja.name == "manga-ocr"

    # 'en' -> rapidocr
    ad_en = await router.resolve_engine(requested_model="en", sample_crops=[make_dummy_crop_bytes()])
    assert ad_en.name == "rapidocr"

    # 'ko' -> rapidocr
    ad_ko = await router.resolve_engine(requested_model="ko", sample_crops=[make_dummy_crop_bytes()])
    assert ad_ko.name == "rapidocr"

    # 'zh' -> rapidocr
    ad_zh = await router.resolve_engine(requested_model="zh", sample_crops=[make_dummy_crop_bytes()])
    assert ad_zh.name == "rapidocr"

    assert rapid_stub.call_count == 0  # All probes bypassed!


@pytest.mark.asyncio
async def test_invalid_model_override_raises_error() -> None:
    """Unknown model string must raise ValueError."""
    router = OCRRouter(
        manga_ocr=StubOCREngine("manga-ocr"),
        rapid_ocr=StubOCREngine("rapidocr"),
    )

    with pytest.raises(ValueError) as exc_info:
        await router.resolve_engine(requested_model="unknown-model")
    assert "Unknown OCR model" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Auto-Probe Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_probe_selects_manga_ocr_for_japanese() -> None:
    """Auto probe returning Japanese text selects MangaOCRAdapter."""
    manga_stub = StubOCREngine("manga-ocr")
    rapid_stub = StubOCREngine("rapidocr", canned_text="何をしているの？")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)

    crop = make_dummy_crop_bytes()
    adapter = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[crop],
    )
    assert adapter.name == "manga-ocr"
    assert rapid_stub.call_count == 1  # RapidOCR was used to probe


@pytest.mark.asyncio
async def test_auto_probe_selects_rapid_ocr_for_latin() -> None:
    """Auto probe returning Latin text selects RapidOCRAdapter."""
    manga_stub = StubOCREngine("manga-ocr")
    rapid_stub = StubOCREngine("rapidocr", canned_text="LOOK OUT!")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)

    crop = make_dummy_crop_bytes()
    adapter = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[crop],
    )
    assert adapter.name == "rapidocr"
    assert rapid_stub.call_count == 1


@pytest.mark.asyncio
async def test_auto_probe_empty_crops_falls_back() -> None:
    """If no sample crops are available, router falls back to default fallback_model."""
    manga_stub = StubOCREngine("manga-ocr")
    rapid_stub = StubOCREngine("rapidocr")

    router = OCRRouter(
        manga_ocr=manga_stub,
        rapid_ocr=rapid_stub,
        fallback_model="manga-ocr",
    )

    adapter = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[],
    )
    assert adapter.name == "manga-ocr"
    assert rapid_stub.call_count == 0


@pytest.mark.asyncio
async def test_auto_probe_exception_falls_back() -> None:
    """If rapid_ocr raises during probe, gracefully fall back to fallback_model."""
    class FailingOCREngine:
        @property
        def name(self) -> str:
            return "rapidocr"

        async def is_available(self) -> bool:
            return True

        async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
            raise RuntimeError("Engine crashed during probe")

    manga_stub = StubOCREngine("manga-ocr")
    failing_rapid = FailingOCREngine()

    router = OCRRouter(
        manga_ocr=manga_stub,
        rapid_ocr=failing_rapid,
        fallback_model="manga-ocr",
    )

    adapter = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[make_dummy_crop_bytes()],
    )
    assert adapter.name == "manga-ocr"


# ---------------------------------------------------------------------------
# Chapter Cache Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chapter_cache_reuses_previous_decision() -> None:
    """Subsequent pages in the same chapter must use cached decision without re-probing."""
    manga_stub = StubOCREngine("manga-ocr")
    rapid_stub = StubOCREngine("rapidocr", canned_text="お前はもう死んでいる")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)

    crop = make_dummy_crop_bytes()
    chapter_id = "one_piece_ch1000"

    # Page 1: Probes and caches result
    adapter1 = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[crop],
        chapter_id=chapter_id,
    )
    assert adapter1.name == "manga-ocr"
    assert rapid_stub.call_count == 1
    assert router.get_cached_model(chapter_id) == "manga-ocr"

    # Page 2: Uses cached result, zero probe calls
    adapter2 = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[crop],
        chapter_id=chapter_id,
    )
    assert adapter2.name == "manga-ocr"
    assert rapid_stub.call_count == 1  # Still 1! No re-probe!

    # Clear cache and verify it probes again
    router.clear_cache()
    assert router.get_cached_model(chapter_id) is None

    adapter3 = await router.resolve_engine(
        requested_model="auto",
        sample_crops=[crop],
        chapter_id=chapter_id,
    )
    assert adapter3.name == "manga-ocr"
    assert rapid_stub.call_count == 2


# ---------------------------------------------------------------------------
# recognize_routed End-to-End Method Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_routed() -> None:
    """recognize_routed resolves engine and transcribes crops in a single call."""
    manga_stub = StubOCREngine("manga-ocr", canned_text="テスト会話")
    rapid_stub = StubOCREngine("rapidocr")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)
    crop = make_dummy_crop_bytes()

    texts, engine_used = await router.recognize_routed(
        image_crops=[crop, crop],
        requested_model="manga-ocr",
    )

    assert engine_used == "manga-ocr"
    assert texts == ["テスト会話", "テスト会話"]
    assert manga_stub.call_count == 1


# ---------------------------------------------------------------------------
# recognize_routed_full_page Tests
# ---------------------------------------------------------------------------


class StubFullPageOCREngine(StubOCREngine):
    """Stub supporting full-page OCR protocol."""

    def __init__(self, name: str, canned_text: str = "") -> None:
        super().__init__(name, canned_text)
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
        return [self.canned_text for _ in work_items]


def make_dummy_work_item(ymin: int = 100, xmin: int = 100, ymax: int = 300, xmax: int = 400) -> BubbleWorkItem:
    from src.backend.detection.base import DetectedBubble

    b = DetectedBubble(id="b_test", box_2d=(ymin, xmin, ymax, xmax))
    return BubbleWorkItem(
        crop_box=(ymin, xmin, ymax, xmax),
        render_box=(ymin, xmin, ymax, xmax),
        parent_bubble=b,
        is_child=False,
        child_index=0,
        confidence=0.95,
    )


@pytest.mark.asyncio
async def test_recognize_routed_full_page_explicit_japanese() -> None:
    """Explicit 'ja' or 'manga-ocr' should crop and route directly to MangaOCR."""
    manga_stub = StubOCREngine("manga-ocr", canned_text="会話文")
    rapid_stub = StubFullPageOCREngine("rapidocr", canned_text="ENGLISH")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)
    dummy_img = Image.new("RGB", (500, 500), color="white")
    work_items = [make_dummy_work_item(), make_dummy_work_item(400, 100, 600, 300)]

    texts, engine_used = await router.recognize_routed_full_page(
        image_np=dummy_img,
        work_items=work_items,
        image_width=500,
        image_height=500,
        requested_model="ja",
    )

    assert engine_used == "manga-ocr"
    assert texts == ["会話文", "会話文"]
    assert manga_stub.call_count == 1
    assert rapid_stub.full_page_calls == 0


@pytest.mark.asyncio
async def test_recognize_routed_full_page_explicit_non_japanese() -> None:
    """Explicit 'en' or 'rapidocr' should execute single-pass full-page recognition without crops."""
    manga_stub = StubOCREngine("manga-ocr", canned_text="会話文")
    rapid_stub = StubFullPageOCREngine("rapidocr", canned_text="ENGLISH DIALOGUE")

    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)
    dummy_img = Image.new("RGB", (500, 500), color="white")
    work_items = [make_dummy_work_item(), make_dummy_work_item(400, 100, 600, 300)]

    texts, engine_used = await router.recognize_routed_full_page(
        image_np=dummy_img,
        work_items=work_items,
        image_width=500,
        image_height=500,
        requested_model="en",
    )

    assert engine_used == "rapidocr"
    assert texts == ["ENGLISH DIALOGUE", "ENGLISH DIALOGUE"]
    assert rapid_stub.full_page_calls == 1
    assert manga_stub.call_count == 0


@pytest.mark.asyncio
async def test_recognize_routed_full_page_auto_detection() -> None:
    """Auto mode probes via RapidOCR full-page, caching selection for the chapter."""
    # 1. Non-Japanese comic (returns English text)
    manga_stub = StubOCREngine("manga-ocr", canned_text="会話文")
    rapid_stub = StubFullPageOCREngine("rapidocr", canned_text="HEY YOU!")
    router = OCRRouter(manga_ocr=manga_stub, rapid_ocr=rapid_stub)

    dummy_img = Image.new("RGB", (500, 500), color="white")
    work_items = [make_dummy_work_item()]
    chapter_id = "chap_non_ja"

    texts, engine_used = await router.recognize_routed_full_page(
        image_np=dummy_img,
        work_items=work_items,
        image_width=500,
        image_height=500,
        requested_model="auto",
        chapter_id=chapter_id,
    )

    assert engine_used == "rapidocr"
    assert texts == ["HEY YOU!"]
    assert router.get_cached_model(chapter_id) == "rapidocr"
    assert rapid_stub.full_page_calls == 1
    assert manga_stub.call_count == 0

    # 2. Japanese manga (RapidOCR full-page detects Kana -> switches to MangaOCR)
    manga_stub_ja = StubOCREngine("manga-ocr", canned_text="にほんご")
    rapid_stub_ja = StubFullPageOCREngine("rapidocr", canned_text="あ、こんにちは")
    router_ja = OCRRouter(manga_ocr=manga_stub_ja, rapid_ocr=rapid_stub_ja)

    chapter_id_ja = "chap_ja"
    texts_ja, engine_used_ja = await router_ja.recognize_routed_full_page(
        image_np=dummy_img,
        work_items=work_items,
        image_width=500,
        image_height=500,
        requested_model="auto",
        chapter_id=chapter_id_ja,
    )

    assert engine_used_ja == "manga-ocr"
    assert texts_ja == ["にほんご"]
    assert router_ja.get_cached_model(chapter_id_ja) == "manga-ocr"
    assert manga_stub_ja.call_count == 1

