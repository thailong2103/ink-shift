"""Shared test fixtures for backend integration testing."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.backend.app import create_app, lifespan
from src.backend.config import Settings

# 1x1 Transparent PNG in standard Base64
SAMPLE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# 1x1 Minimal JPEG in standard Base64
SAMPLE_JPEG_BASE64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP////////////////////////////////////////////////"
    "//////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAA"
    "AP/aAAgBAQABPxA="
)

SAMPLE_IMAGE_HASH = "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e"


@pytest.fixture
def temp_settings(tmp_path: Path) -> Settings:
    """Return Settings configured with an isolated temporary SQLite database."""
    db_file = tmp_path / "test_cache.db"
    return Settings(
        inkshift_db_path=str(db_file),
        inkshift_default_engine="mock",
    )


@pytest.fixture
def test_app(temp_settings: Settings) -> FastAPI:
    """Create FastAPI application configured with temporary test settings."""
    return create_app(temp_settings)


import pytest_asyncio


@pytest_asyncio.fixture
async def async_client(test_app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an HTTPX AsyncClient connected to test application with active lifespan."""
    async with lifespan(test_app):
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
        ) as client:
            yield client


@pytest.fixture
def client_headers() -> dict[str, str]:
    """Valid security headers for extension client requests."""
    return {
        "X-InkShift-Client": "extension",
    }


@pytest.fixture
def sample_translation_payload() -> dict[str, Any]:
    """Standard valid translation request payload dictionary."""
    return {
        "image": SAMPLE_PNG_BASE64,
        "image_hash": SAMPLE_IMAGE_HASH,
        "source_lang": "ja",
        "target_lang": "vi",
        "engine": "mock",
        "force_refresh": False,
    }
