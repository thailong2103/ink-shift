"""Unit tests for API Gateway Option G1 shared detection and engine-isolated caching."""

from __future__ import annotations

import base64
import io
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from src.backend.app import create_app, lifespan
from src.backend.config import Settings
from src.backend.detection.base import DetectedBubble
from src.backend.engines.base import BaseTranslationEngine
from src.backend.schemas.contract import (
    TranslatedBlock,
    TranslationRequest,
    TranslationResponse,
)


def _generate_test_image_b64(width: int = 200, height: int = 300) -> str:
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class StubEngine(BaseTranslationEngine):
    """Stub engine recording received bubbles."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.received_bubbles: list[list[DetectedBubble] | None] = []

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return True

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        self.received_bubbles.append(bubbles)
        return TranslationResponse(
            success=True,
            page_hash=request.image_hash or "test_hash",
            engine_used=self._name,
            execution_time_ms=50,
            from_cache=False,
            blocks=[
                TranslatedBlock(
                    id="blk_0",
                    box=(100, 100, 200, 200),
                    source_text="Test",
                    translated_text="Thử nghiệm",
                )
            ],
        )


@pytest.mark.asyncio
async def test_gateway_option_g1_detection_lifecycle(tmp_path: Any) -> None:
    """Option G1: shared detector runs once on cache miss, bubbles passed to engine, bypassed on cache hit."""
    db_file = str(tmp_path / "gateway_test.db")
    settings = Settings(inkshift_db_path=db_file)
    app = create_app(settings)

    mock_detector = AsyncMock()
    detected_bubbles = [
        DetectedBubble(id="b1", box_2d=(50, 50, 150, 150), confidence=0.99),
    ]
    mock_detector.detect = AsyncMock(return_value=detected_bubbles)

    local_stub = StubEngine(name="local")
    cloud_stub = StubEngine(name="cloud")
    mock_stub = StubEngine(name="mock")

    async with lifespan(app):
        # Configure app state
        app.state.detector = mock_detector
        app.state.registry.register(local_stub)
        app.state.registry.register(cloud_stub)
        app.state.registry.register(mock_stub)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-InkShift-Client": "extension"}
            image_b64 = _generate_test_image_b64(width=400, height=600)

            hash_1 = "a" * 64
            hash_2 = "b" * 64

            # 1. First local request (Cache MISS): should run detection
            req1 = {
                "image": image_b64,
                "image_hash": hash_1,
                "source_lang": "ja",
                "target_lang": "vi",
                "engine": "local",
            }
            resp1 = await client.post("/api/v1/translate", json=req1, headers=headers)
            assert resp1.status_code == 200
            assert resp1.json()["from_cache"] is False
            assert mock_detector.detect.call_count == 1
            # Verify width and height forwarded to detect
            _, orig_w, orig_h = mock_detector.detect.call_args[0]
            assert orig_w == 400
            assert orig_h == 600
            # Verify engine received bubbles
            assert len(local_stub.received_bubbles) == 1
            assert local_stub.received_bubbles[0] == detected_bubbles

            # 2. Second local request (Cache HIT): detection must NOT run again
            resp2 = await client.post("/api/v1/translate", json=req1, headers=headers)
            assert resp2.status_code == 200
            assert resp2.json()["from_cache"] is True
            assert mock_detector.detect.call_count == 1  # Unchanged!

            # 3. Third request with engine='cloud' for SAME image:
            # Cache must isolate by engine -> Cache MISS for 'cloud' -> detector runs again!
            req3 = dict(req1)
            req3["engine"] = "cloud"
            resp3 = await client.post("/api/v1/translate", json=req3, headers=headers)
            assert resp3.status_code == 200
            assert resp3.json()["from_cache"] is False
            assert resp3.json()["engine_used"] == "cloud"
            assert mock_detector.detect.call_count == 2
            assert len(cloud_stub.received_bubbles) == 1
            assert cloud_stub.received_bubbles[0] == detected_bubbles

            # 4. Request with engine='mock': detector must be BYPASSED entirely
            req4 = dict(req1)
            req4["engine"] = "mock"
            req4["image_hash"] = hash_2
            resp4 = await client.post("/api/v1/translate", json=req4, headers=headers)
            assert resp4.status_code == 200
            assert resp4.json()["engine_used"] == "mock"
            assert mock_detector.detect.call_count == 2  # Detector was NOT called!
            assert len(mock_stub.received_bubbles) == 1
            assert mock_stub.received_bubbles[0] is None  # Mock received None
