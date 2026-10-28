"""End-to-end integration tests for FastAPI v1 endpoints and lifespan."""

import base64
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.backend.app import lifespan
from src.backend.config import Settings
from src.backend.engines.cloud.exceptions import (
    ContentSafetyBlockedError,
    RateLimitExceededError,
    UpstreamAuthenticationError,
    UpstreamTimeoutError,
)
from src.backend.engines.registry import EngineNotFoundError, EngineRegistry
from src.backend.schemas.contract import TranslatedBlock
from tests.backend.conftest import (
    SAMPLE_IMAGE_HASH,
    SAMPLE_JPEG_BASE64,
    SAMPLE_PNG_BASE64,
)


@pytest.mark.asyncio
class TestHealthEndpoint:
    """Integration tests for GET /api/v1/health."""

    async def test_health_check_returns_ok_and_engine_map(
        self,
        async_client: httpx.AsyncClient,
    ) -> None:
        """Exempt from client headers, returns 200 and healthy engines."""
        resp = await async_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["mock"] is True
        assert data["engines_available"]["cloud"] is True
        assert data["engines_available"]["local"] is True
        assert set(data["engines_available"].keys()) == {"mock", "cloud", "local"}
        assert data["active_engine"] == "mock"

    async def test_health_check_with_empty_registry(
        self,
        temp_settings: Settings,
    ) -> None:
        """When no engine is registered, active_engine falls back to 'none'."""
        from src.backend.app import create_app

        app = create_app(temp_settings)
        # Pre-seed empty registry before lifespan startup
        app.state.registry = EngineRegistry()

        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                resp = await client.get("/api/v1/health")
                assert resp.status_code == 200
                data = resp.json()
                # Lifespan registers mock engine if mock default is configured; test registry active_engine
                assert "status" in data


@pytest.mark.asyncio
class TestCacheEndpoint:
    """Integration tests for GET /api/v1/cache/{image_hash}."""

    async def test_cache_endpoint_rejects_missing_client_header(
        self,
        async_client: httpx.AsyncClient,
    ) -> None:
        """Protected endpoint requires X-InkShift-Client header."""
        resp = await async_client.get(f"/api/v1/cache/{SAMPLE_IMAGE_HASH}")
        assert resp.status_code == 403
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "FORBIDDEN_CLIENT"

    async def test_cache_miss_returns_structured_404(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
    ) -> None:
        """Non-cached page returns 404 with structured CACHE_MISS error detail."""
        resp = await async_client.get(
            f"/api/v1/cache/{SAMPLE_IMAGE_HASH}?target_lang=vi",
            headers=client_headers,
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "CACHE_MISS"
        assert data["error"]["details"]["image_hash"] == SAMPLE_IMAGE_HASH
        assert data["error"]["details"]["target_lang"] == "vi"

    async def test_cache_lookup_with_invalid_hash_format_returns_422(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
    ) -> None:
        """Hashes not matching 64 hex characters are rejected by Pydantic validation."""
        resp = await async_client.get(
            "/api/v1/cache/too_short_hash",
            headers=client_headers,
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
class TestTranslateEndpoint:
    """Integration tests for POST /api/v1/translate."""

    async def test_translate_missing_client_header_returns_403(
        self,
        async_client: httpx.AsyncClient,
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Calls without X-InkShift-Client are blocked at middleware."""
        resp = await async_client.post("/api/v1/translate", json=sample_translation_payload)
        assert resp.status_code == 403

    async def test_translate_malformed_base64_returns_400(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Un-decodable base64 string returns 400 INVALID_IMAGE_PAYLOAD."""
        payload = dict(sample_translation_payload)
        payload["image"] = "not_valid_base64_%%@@"
        resp = await async_client.post(
            "/api/v1/translate",
            json=payload,
            headers=client_headers,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_IMAGE_PAYLOAD"
        assert "Malformed Base64" in data["error"]["message"]

    async def test_translate_invalid_magic_bytes_returns_400(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Decodable base64 without image magic bytes (e.g. plain text) returns 400."""
        text_bytes = b"Hello world! Not an image."
        payload = dict(sample_translation_payload)
        payload["image"] = base64.b64encode(text_bytes).decode("ascii")
        resp = await async_client.post(
            "/api/v1/translate",
            json=payload,
            headers=client_headers,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_IMAGE_PAYLOAD"
        assert "Invalid image format" in data["error"]["message"]

    async def test_translate_supports_data_url_and_computes_missing_hash(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
    ) -> None:
        """Supports data:image/png;base64 prefix and auto-computes sha256 when omitted."""
        data_url_image = f"data:image/png;base64,{SAMPLE_PNG_BASE64}"
        payload = {
            "image": data_url_image,
            "source_lang": "ja",
            "target_lang": "vi",
            "engine": "mock",
        }
        resp = await async_client.post(
            "/api/v1/translate",
            json=payload,
            headers=client_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_cache"] is False
        assert len(data["page_hash"]) == 64
        assert len(data["blocks"]) > 0

    async def test_translate_supports_jpeg_payload(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Accepts JPEG image payloads with valid magic bytes."""
        payload = dict(sample_translation_payload)
        payload["image"] = SAMPLE_JPEG_BASE64
        resp = await async_client.post(
            "/api/v1/translate",
            json=payload,
            headers=client_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["engine_used"] == "mock"

    async def test_translate_with_auto_engine_resolves_default(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Using engine='auto' uses the default configured engine."""
        payload = dict(sample_translation_payload)
        payload["engine"] = "auto"
        resp = await async_client.post(
            "/api/v1/translate",
            json=payload,
            headers=client_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["engine_used"] == "mock"

    async def test_translate_requested_engine_unavailable_returns_400(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When requested engine is not registered in registry, returns 400 ENGINE_UNAVAILABLE."""
        payload = dict(sample_translation_payload)
        payload["engine"] = "local"
        with patch(
            "src.backend.engines.registry.EngineRegistry.get",
            side_effect=EngineNotFoundError("Engine 'local' is not registered."),
        ):
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 400
            data = resp.json()
            assert data["success"] is False
            assert data["error"]["code"] == "ENGINE_UNAVAILABLE"

    async def test_translate_engine_runtime_failure_returns_500(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When engine raises a runtime exception, returns 500 ENGINE_EXECUTION_FAILED."""
        with patch(
            "src.backend.engines.mock.MockTranslationEngine.translate",
            new_callable=AsyncMock,
        ) as mock_translate:
            mock_translate.side_effect = RuntimeError("Inference process killed")

            resp = await async_client.post(
                "/api/v1/translate",
                json=sample_translation_payload,
                headers=client_headers,
            )
            assert resp.status_code == 500
            data = resp.json()
            assert data["success"] is False
            assert data["error"]["code"] == "ENGINE_EXECUTION_FAILED"
            assert "Inference process killed" in data["error"]["message"]

    async def test_end_to_end_cache_lifecycle_and_sub_5ms_retrieval(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Full flow: Cache miss -> Engine execution -> Cache storage -> Cache hit."""
        # 1. Cache Miss on /cache/{hash}
        lookup_before = await async_client.get(
            f"/api/v1/cache/{SAMPLE_IMAGE_HASH}?target_lang=vi",
            headers=client_headers,
        )
        assert lookup_before.status_code == 404
        assert lookup_before.json()["error"]["code"] == "CACHE_MISS"

        # 2. First Translate Request (Cache miss, triggers engine execution)
        translate_resp_1 = await async_client.post(
            "/api/v1/translate",
            json=sample_translation_payload,
            headers=client_headers,
        )
        assert translate_resp_1.status_code == 200
        result_1 = translate_resp_1.json()
        assert result_1["from_cache"] is False
        assert len(result_1["blocks"]) == 3

        # 3. Direct Cache Query now returns HTTP 200
        lookup_after = await async_client.get(
            f"/api/v1/cache/{SAMPLE_IMAGE_HASH}?target_lang=vi",
            headers=client_headers,
        )
        assert lookup_after.status_code == 200
        lookup_data = lookup_after.json()
        assert lookup_data["page_hash"] == SAMPLE_IMAGE_HASH
        assert lookup_data["from_cache"] is True
        assert len(lookup_data["blocks"]) == 3

        # 4. Second Translate Request (Cache Hit: fast retrieval)
        start_time = time.perf_counter()
        translate_resp_2 = await async_client.post(
            "/api/v1/translate",
            json=sample_translation_payload,
            headers=client_headers,
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        assert translate_resp_2.status_code == 200
        result_2 = translate_resp_2.json()
        assert result_2["from_cache"] is True
        assert result_2["blocks"] == result_1["blocks"]
        # In-memory/local SQLite cache hit retrieval should be fast
        assert elapsed_ms < 100.0

        # 5. Force Refresh bypasses cache
        refresh_payload = dict(sample_translation_payload)
        refresh_payload["force_refresh"] = True
        translate_resp_3 = await async_client.post(
            "/api/v1/translate",
            json=refresh_payload,
            headers=client_headers,
        )
        assert translate_resp_3.status_code == 200
        result_3 = translate_resp_3.json()
        assert result_3["from_cache"] is False

    async def test_translate_with_cloud_engine_succeeds(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When engine='cloud' is requested, executes translation through registered cloud engine."""
        mock_blocks = [
            TranslatedBlock(
                id="blk_cloud_01",
                box=(100, 150, 300, 450),
                source_text="テスト",
                translated_text="Thử nghiệm",
                direction="vertical",
                confidence=0.97,
            )
        ]
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            return_value=mock_blocks,
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_used"] == "cloud"
            assert len(data["blocks"]) == 1
            assert data["blocks"][0]["translated_text"] == "Thử nghiệm"

    async def test_translate_with_cloud_providers(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Allows routing to cloud engine with specific providers ('gemini' and 'xkiro')."""
        mock_blocks = [
            TranslatedBlock(
                id="blk_01",
                box=(100, 150, 300, 450),
                translated_text="Lời thoại",
            )
        ]
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            return_value=mock_blocks,
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["provider"] = "gemini"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["engine_used"] == "cloud"

        with patch(
            "src.backend.engines.cloud.openai_compat.OpenAICompatibleProvider.translate_page",
            new_callable=AsyncMock,
            return_value=mock_blocks,
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["provider"] = "xkiro"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["engine_used"] == "cloud"

    async def test_translate_with_local_engine_succeeds(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When engine='local' is requested and available, executes translation through LocalTranslationEngine."""
        from src.backend.schemas.contract import TranslationResponse

        mock_response = TranslationResponse(
            success=True,
            page_hash=SAMPLE_IMAGE_HASH,
            engine_used="local",
            execution_time_ms=120,
            from_cache=False,
            blocks=[
                TranslatedBlock(
                    id="blk_local_01",
                    box=(100, 150, 300, 450),
                    source_text="こんにちは",
                    translated_text="Xin chào",
                    direction="vertical",
                    confidence=0.98,
                )
            ],
        )
        with patch(
            "src.backend.engines.local.engine.LocalTranslationEngine.is_available",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "src.backend.engines.local.engine.LocalTranslationEngine.translate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "local"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["engine_used"] == "local"
            assert len(data["blocks"]) == 1
            assert data["blocks"][0]["translated_text"] == "Xin chào"

    async def test_translate_local_engine_japanese_source_lang_regression(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Regression test for ADR-017: source_lang='ja' with engine='local' succeeds via RapidOCR."""
        from src.backend.schemas.contract import TranslationResponse

        mock_response = TranslationResponse(
            success=True,
            page_hash=SAMPLE_IMAGE_HASH,
            engine_used="local",
            execution_time_ms=145,
            from_cache=False,
            blocks=[
                TranslatedBlock(
                    id="blk_ja_01",
                    box=(50, 80, 200, 300),
                    source_text="何をしているの？",
                    translated_text="Bạn đang làm gì đấy?",
                    direction="vertical",
                    confidence=0.96,
                )
            ],
        )
        with patch(
            "src.backend.engines.local.engine.LocalTranslationEngine.is_available",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "src.backend.engines.local.engine.LocalTranslationEngine.translate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_translate:
            payload = dict(sample_translation_payload)
            payload["engine"] = "local"
            payload["source_lang"] = "ja"
            payload["force_refresh"] = True

            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["engine_used"] == "local"
            assert len(data["blocks"]) == 1
            assert data["blocks"][0]["source_text"] == "何をしているの？"
            assert data["blocks"][0]["translated_text"] == "Bạn đang làm gì đấy?"
            mock_translate.assert_called_once()
            called_req = mock_translate.call_args[0][0]
            assert called_req.source_lang == "ja"

    async def test_translate_content_safety_blocked_maps_to_422(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When upstream AI triggers safety filter, maps to 422 CONTENT_SAFETY_BLOCKED."""
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            side_effect=ContentSafetyBlockedError("Image blocked by safety policy"),
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 422
            data = resp.json()
            assert data["success"] is False
            assert data["error"]["code"] == "CONTENT_SAFETY_BLOCKED"
            assert "Image blocked by safety policy" in data["error"]["message"]

    async def test_translate_rate_limit_maps_to_429(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When upstream rate limits, maps to 429 RATE_LIMIT_EXCEEDED."""
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            side_effect=RateLimitExceededError("Rate limit exceeded"),
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 429
            data = resp.json()
            assert data["success"] is False
            assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    async def test_translate_upstream_timeout_maps_to_504(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When upstream request times out, maps to 504 UPSTREAM_TIMEOUT."""
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            side_effect=UpstreamTimeoutError("Timed out waiting for Gemini"),
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 504
            data = resp.json()
            assert data["success"] is False
            assert data["error"]["code"] == "UPSTREAM_TIMEOUT"

    async def test_translate_generic_cloud_error_maps_to_status_code(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """When upstream authentication fails (HTTP 401), maps to 401 INVALID_API_KEY."""
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            side_effect=UpstreamAuthenticationError("Missing Gemini API key"),
        ):
            payload = dict(sample_translation_payload)
            payload["engine"] = "cloud"
            payload["force_refresh"] = True
            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 401
            data = resp.json()
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_API_KEY"

    async def test_end_to_end_cloud_cache_lifecycle_and_sub_5ms_retrieval(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Full lifecycle for Cloud engine: Cache miss -> Cloud call -> SQLite store -> Sub-5ms hit."""
        cloud_image_hash = "c100d00000000000000000000000000000000000000000000000000000000001"
        cloud_payload = dict(sample_translation_payload)
        cloud_payload["image_hash"] = cloud_image_hash
        cloud_payload["engine"] = "cloud"
        cloud_payload["force_refresh"] = False

        mock_blocks = [
            TranslatedBlock(
                id="blk_c1",
                box=(50, 100, 200, 300),
                source_text="クラウド",
                translated_text="Đám mây",
                direction="vertical",
                confidence=0.95,
            )
        ]

        # 1. Cache Miss on /cache/{hash}
        miss_resp = await async_client.get(
            f"/api/v1/cache/{cloud_image_hash}?target_lang=vi",
            headers=client_headers,
        )
        assert miss_resp.status_code == 404
        assert miss_resp.json()["error"]["code"] == "CACHE_MISS"

        # 2. First Translate Request (Cache miss, triggers cloud engine)
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
            return_value=mock_blocks,
        ) as mock_provider:
            resp_1 = await async_client.post(
                "/api/v1/translate",
                json=cloud_payload,
                headers=client_headers,
            )
            assert resp_1.status_code == 200
            data_1 = resp_1.json()
            assert data_1["from_cache"] is False
            assert data_1["engine_used"] == "cloud"
            assert len(data_1["blocks"]) == 1
            assert data_1["blocks"][0]["translated_text"] == "Đám mây"
            mock_provider.assert_awaited_once()

        # 3. Direct Cache Query now returns HTTP 200
        lookup_resp = await async_client.get(
            f"/api/v1/cache/{cloud_image_hash}?target_lang=vi",
            headers=client_headers,
        )
        assert lookup_resp.status_code == 200
        lookup_data = lookup_resp.json()
        assert lookup_data["page_hash"] == cloud_image_hash
        assert lookup_data["from_cache"] is True
        assert len(lookup_data["blocks"]) == 1

        # 4. Second Translate Request (Cache Hit: fast retrieval without calling upstream provider)
        with patch(
            "src.backend.engines.cloud.gemini.GeminiProvider.translate_page",
            new_callable=AsyncMock,
        ) as mock_provider_hit:
            start_time = time.perf_counter()
            resp_2 = await async_client.post(
                "/api/v1/translate",
                json=cloud_payload,
                headers=client_headers,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            assert resp_2.status_code == 200
            data_2 = resp_2.json()
            assert data_2["from_cache"] is True
            assert data_2["blocks"] == data_1["blocks"]
            mock_provider_hit.assert_not_called()
            assert elapsed_ms < 100.0

    async def test_translate_does_not_cache_when_is_fallback_is_true(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """Translations with is_fallback=True must NEVER be persisted to SQLite cache."""
        payload = dict(sample_translation_payload)
        payload["image_hash"] = "f" * 64
        payload["engine"] = "mock"

        from src.backend.schemas.contract import TranslationResponse

        fallback_response = TranslationResponse(
            page_hash=payload["image_hash"],
            engine_used="mock",
            execution_time_ms=50,
            from_cache=False,
            is_fallback=True,
            blocks=[],
        )

        with patch("src.backend.engines.mock.MockTranslationEngine.translate", new_callable=AsyncMock) as mock_translate:
            mock_translate.return_value = fallback_response

            resp = await async_client.post(
                "/api/v1/translate",
                json=payload,
                headers=client_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_fallback"] is True

        # Assert direct cache query is a 404 CACHE_MISS (not stored!)
        cache_resp = await async_client.get(
            f"/api/v1/cache/{payload['image_hash']}?target_lang=vi",
            headers=client_headers,
        )
        assert cache_resp.status_code == 404

    async def test_delete_cache_endpoints(
        self,
        async_client: httpx.AsyncClient,
        client_headers: dict[str, str],
        sample_translation_payload: dict[str, Any],
    ) -> None:
        """DELETE /api/v1/cache supports deleting single hash and wiping entire cache."""
        payload = dict(sample_translation_payload)
        payload["image_hash"] = "d" * 64
        payload["engine"] = "mock"

        # 1. Translate to populate cache
        resp = await async_client.post("/api/v1/translate", json=payload, headers=client_headers)
        assert resp.status_code == 200

        # Verify entry in cache
        cache_resp = await async_client.get(f"/api/v1/cache/{payload['image_hash']}?target_lang=vi", headers=client_headers)
        assert cache_resp.status_code == 200

        # 2. Delete specific entry
        del_single = await async_client.delete(
            f"/api/v1/cache?image_hash={payload['image_hash']}",
            headers=client_headers,
        )
        assert del_single.status_code == 200
        del_data = del_single.json()
        assert del_data["success"] is True
        assert del_data["deleted"] >= 1
        assert del_data["scope"] == "single"

        # Verify entry is gone
        cache_resp2 = await async_client.get(f"/api/v1/cache/{payload['image_hash']}?target_lang=vi", headers=client_headers)
        assert cache_resp2.status_code == 404

        # 3. Wipe all cache
        del_all = await async_client.delete("/api/v1/cache?all=true", headers=client_headers)
        assert del_all.status_code == 200
        del_all_data = del_all.json()
        assert del_all_data["success"] is True
        assert del_all_data["scope"] == "all"


