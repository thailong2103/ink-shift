"""End-to-end integration tests and latency benchmark for Module 5 (local-engine)."""

from __future__ import annotations

import base64
import hashlib
import io
import time
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from PIL import Image, ImageDraw

from src.backend.app import create_app
from src.backend.config import Settings
from src.backend.detection.base import DetectedBubble
from src.backend.engines.local.engine import LocalTranslationEngine
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.schemas.contract import TranslationRequest

# ---------------------------------------------------------------------------
# Test Page Generator
# ---------------------------------------------------------------------------


def generate_synthetic_manga_page(width: int = 800, height: int = 1200) -> bytes:
    """Generate a synthetic manga page with 3 drawn speech bubbles."""
    img = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)

    # Bubble 1: Top-right vertical dialogue (100, 500) to (350, 750)
    draw.ellipse([500, 100, 750, 350], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
    # Bubble 2: Middle-left horizontal dialogue (450, 100) to (650, 400)
    draw.ellipse([100, 450, 400, 650], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
    # Bubble 3: Bottom action SFX (800, 250) to (1100, 550)
    draw.ellipse([250, 800, 550, 1100], fill=(255, 255, 255), outline=(0, 0, 0), width=3)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Stub Implementations for E2E Pipeline
# ---------------------------------------------------------------------------


class E2EDetector:
    """Simulates ComicTextDetector output for the synthetic manga page."""

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def name(self) -> str:
        return "e2e-detector"

    async def is_available(self) -> bool:
        return True

    async def detect(
        self, image_bytes: bytes, original_width: int, original_height: int
    ) -> list[DetectedBubble]:
        self.call_count += 1
        # Returns normalized [0, 1000] bounding boxes for the 3 drawn bubbles
        # Bubble 1: y=[100/1200, 350/1200], x=[500/800, 750/800] -> [83, 625, 292, 938]
        # Bubble 2: y=[450/1200, 650/1200], x=[100/800, 400/800] -> [375, 125, 542, 500]
        # Bubble 3: y=[800/1200, 1100/1200], x=[250/800, 550/800] -> [667, 312, 917, 688]
        return [
            DetectedBubble(id="1", box_2d=(83, 625, 292, 938), confidence=0.98),
            DetectedBubble(id="2", box_2d=(375, 125, 542, 500), confidence=0.95),
            DetectedBubble(id="3", box_2d=(667, 312, 917, 688), confidence=0.91),
        ]

    async def detect_layout(
        self, image_bytes: bytes, original_width: int, original_height: int
    ) -> tuple[list[DetectedBubble], list[Any]]:
        bubbles = await self.detect(image_bytes, original_width, original_height)
        return bubbles, []


class E2EJapaneseOCR:
    """Simulates MangaOCR specialized Japanese recognition."""

    @property
    def name(self) -> str:
        return "manga-ocr"

    async def is_available(self) -> bool:
        return True

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        # Canned Japanese manga dialogue matching the 3 bubbles
        return [
            "お前は一体誰だ？！",
            "逃げろ、早く！",
            "ドカン！！",
        ]


class E2ERapidOCR:
    """Simulates RapidOCR probe and multilingual recognition."""

    @property
    def name(self) -> str:
        return "rapidocr"

    async def is_available(self) -> bool:
        return True

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        # Probe detects Hiragana/Katakana from first bubble
        return ["お前は一体誰だ？！"]


class E2ETranslator:
    """Simulates GoogleFreeTranslator zero-cost batch translation."""

    @property
    def name(self) -> str:
        return "google-free"

    async def is_available(self) -> bool:
        return True

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str | None = None,
    ) -> list[str]:
        # Return fluent Vietnamese manga translations
        translation_dict = {
            "お前は一体誰だ？！": "Rốt cuộc ngươi là ai?!",
            "逃げろ、早く！": "Chạy đi, mau lên!",
            "ドカン！！": "ĐOÀNG!!",
        }
        return [translation_dict.get(t, f"dịch: {t}") for t in texts]


# ---------------------------------------------------------------------------
# End-to-End Test Suite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_local_translation_pipeline() -> None:
    """Full lifecycle: synthetic page -> DirectML detector -> OCR router -> batch translation -> response."""
    detector = E2EDetector()
    manga_ocr = E2EJapaneseOCR()
    rapid_ocr = E2ERapidOCR()
    router = OCRRouter(manga_ocr=manga_ocr, rapid_ocr=rapid_ocr, default_model="auto")
    translator = E2ETranslator()

    engine = LocalTranslationEngine(
        detector=detector,
        ocr_router=router,
        translator=translator,
        name="local",
        default_ocr="auto",
    )

    page_bytes = generate_synthetic_manga_page()
    page_b64 = base64.b64encode(page_bytes).decode("utf-8")
    expected_hash = hashlib.sha256(page_bytes).hexdigest()

    req = TranslationRequest(
        image=page_b64,
        source_lang="ja",
        target_lang="vi",
        engine="local",
    )

    start_perf = time.perf_counter()
    resp = await engine.translate(req)
    total_latency_ms = (time.perf_counter() - start_perf) * 1000

    # 1. Verification of latency constraint (Budget: <= 2500ms)
    assert total_latency_ms < 2500.0, f"Latency exceeded budget: {total_latency_ms:.2f}ms"

    # 2. Canonical TranslationResponse verification
    assert resp.success is True
    assert resp.page_hash == expected_hash
    assert resp.engine_used == "local"
    assert resp.from_cache is False
    assert len(resp.blocks) == 3

    # 3. Block Coordinate Geometry & Content Verification
    b0, b1, b2 = resp.blocks

    # Block 0: Top-right dialogue
    assert b0.id == "blk_0"
    assert b0.box == (83, 625, 292, 938)
    assert b0.source_text == "お前は一体誰だ？！"
    assert b0.translated_text == "Rốt cuộc ngươi là ai?!"
    assert b0.confidence == 0.98

    # Block 1: Middle-left dialogue
    assert b1.id == "blk_1"
    assert b1.box == (375, 125, 542, 500)
    assert b1.source_text == "逃げろ、早く！"
    assert b1.translated_text == "Chạy đi, mau lên!"
    assert b1.confidence == 0.95

    # Block 2: Bottom SFX
    assert b2.id == "blk_2"
    assert b2.box == (667, 312, 917, 688)
    assert b2.source_text == "ドカン！！"
    assert b2.translated_text == "ĐOÀNG!!"
    assert b2.confidence == 0.91

    # Verify all coordinates strictly bounded in [0, 1000]
    for blk in resp.blocks:
        ymin, xmin, ymax, xmax = blk.box
        assert 0 <= ymin < ymax <= 1000
        assert 0 <= xmin < xmax <= 1000


@pytest.mark.asyncio
async def test_e2e_http_endpoint_with_local_engine(tmp_path: Any) -> None:
    """HTTP Client POST /api/v1/translate with engine='local' integrates seamlessly through FastAPI."""
    db_file = str(tmp_path / "e2e_cache.db")
    settings = Settings(
        inkshift_db_path=db_file,
        inkshift_default_engine="local",
    )
    app = create_app(settings)

    # Mock the internal engines for HTTP level integration test
    mock_engine = LocalTranslationEngine(
        detector=E2EDetector(),
        ocr_router=OCRRouter(E2EJapaneseOCR(), E2ERapidOCR()),
        translator=E2ETranslator(),
        name="local",
    )

    page_bytes = generate_synthetic_manga_page()
    page_b64 = base64.b64encode(page_bytes).decode("utf-8")

    from src.backend.app import lifespan

    async with (
        lifespan(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        app.state.detector = E2EDetector()
        # Patch registry's local engine to ensure availability during HTTP test
        with patch.object(app.state.registry, "get", return_value=mock_engine):
                payload = {
                    "image": page_b64,
                    "source_lang": "ja",
                    "target_lang": "vi",
                    "engine": "local",
                }
                headers = {"X-InkShift-Client": "extension"}

                # First request: Fresh translation (Cache MISS)
                resp1 = await client.post("/api/v1/translate", json=payload, headers=headers)
                assert resp1.status_code == 200
                data1 = resp1.json()
                assert data1["success"] is True
                assert data1["engine_used"] == "local"
                assert data1["from_cache"] is False
                assert len(data1["blocks"]) == 3

                # Second request: Cache HIT (Sub-5ms retrieval from SQLite)
                resp2 = await client.post("/api/v1/translate", json=payload, headers=headers)
                assert resp2.status_code == 200
                data2 = resp2.json()
                assert data2["success"] is True
                assert data2["from_cache"] is True
                assert data2["blocks"] == data1["blocks"]
