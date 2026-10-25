"""Integration tests for backend concurrency controls, local semaphore, and singleflight deduplication."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.backend.app import lifespan
from src.backend.schemas.contract import TranslationResponse
from tests.backend.conftest import SAMPLE_IMAGE_HASH, SAMPLE_PNG_BASE64


@pytest.mark.asyncio
async def test_concurrent_identical_requests_single_execution(
    test_app: FastAPI,
    client_headers: dict[str, str],
) -> None:
    """Verify that multiple concurrent requests for the same image hash execute engine inference exactly once."""
    async with lifespan(test_app):
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            mock_engine = test_app.state.registry.get("mock")
            original_translate = mock_engine.translate
            call_count = 0

            async def slow_translate(*args: Any, **kwargs: Any) -> TranslationResponse:
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.1)  # Simulate model latency
                return await original_translate(*args, **kwargs)

            mock_engine.translate = slow_translate

            payload = {
                "image": SAMPLE_PNG_BASE64,
                "image_hash": SAMPLE_IMAGE_HASH,
                "source_lang": "ja",
                "target_lang": "vi",
                "engine": "mock",
                "force_refresh": True,  # Force bypass cache to trigger in-flight lock
            }

            # Fire 5 concurrent requests with identical page_hash
            tasks = [
                client.post("/api/v1/translate", json=payload, headers=client_headers)
                for _ in range(5)
            ]
            responses = await asyncio.gather(*tasks)

            # All 5 callers must receive HTTP 200 and success=True
            for resp in responses:
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["page_hash"] == SAMPLE_IMAGE_HASH

            # Engine inference must have executed exactly 1 time
            assert call_count == 1

            # In-flight map must be empty
            assert len(test_app.state.in_flight_tasks) == 0


@pytest.mark.asyncio
async def test_in_flight_cleanup_on_error(
    test_app: FastAPI,
    client_headers: dict[str, str],
) -> None:
    """Verify in-flight map is cleanly evacuated even if translation raises an error."""
    async with lifespan(test_app):
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            mock_engine = test_app.state.registry.get("mock")

            async def failing_translate(*args: Any, **kwargs: Any) -> TranslationResponse:
                await asyncio.sleep(0.05)
                raise RuntimeError("Simulated inference engine crash")

            mock_engine.translate = failing_translate

            payload = {
                "image": SAMPLE_PNG_BASE64,
                "image_hash": SAMPLE_IMAGE_HASH,
                "source_lang": "ja",
                "target_lang": "vi",
                "engine": "mock",
                "force_refresh": True,
            }

            tasks = [
                client.post("/api/v1/translate", json=payload, headers=client_headers)
                for _ in range(3)
            ]
            responses = await asyncio.gather(*tasks)

            for resp in responses:
                assert resp.status_code == 500
                assert resp.json()["success"] is False

            # In-flight map must be clean
            assert len(test_app.state.in_flight_tasks) == 0


@pytest.mark.asyncio
async def test_local_semaphore_initialization(test_app: FastAPI) -> None:
    """Verify app.state.local_semaphore is configured with value 1."""
    async with lifespan(test_app):
        sem = test_app.state.local_semaphore
        assert isinstance(sem, asyncio.Semaphore)
        # Verify it only allows 1 acquisition concurrently
        async with sem:
            assert sem.locked()
