"""Integration tests for Manga Context Graph REST API endpoints."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_context_report_endpoint(
    async_client: httpx.AsyncClient,
    client_headers: dict[str, str],
) -> None:
    """Verify POST /api/v1/context/report registers series, chapter, and page manifest."""
    payload = {
        "series_id": "mangadex:uuid-series-001",
        "series_title": "Dungeon Meshi",
        "source_domain": "mangadex.org",
        "cover_url": "https://cdn.example.com/cover.jpg",
        "chapter_id": "chapter-dm-01",
        "chapter_ordinal": 1.0,
        "chapter_label": "Ch. 1 - Hot Pot",
        "chapter_url": "https://mangadex.org/chapter/dm-01/1",
        "total_pages": 3,
        "pages": [
            {"page_number": 1, "image_url": "https://cdn/dm1.jpg"},
            {"page_number": 2, "image_url": "https://cdn/dm2.jpg"},
            {"page_number": 3, "image_url": "https://cdn/dm3.jpg"},
        ],
    }

    # 1. Without client header -> 403 Forbidden
    resp_no_header = await async_client.post("/api/v1/context/report", json=payload)
    assert resp_no_header.status_code == 403

    # 2. With valid client header -> 200 OK
    resp = await async_client.post(
        "/api/v1/context/report",
        json=payload,
        headers=client_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["chapter_id"] == "chapter-dm-01"
    assert data["series_id"] == "mangadex:uuid-series-001"
    assert data["pages_registered"] == 3


@pytest.mark.asyncio
async def test_reading_progress_endpoint(
    async_client: httpx.AsyncClient,
    client_headers: dict[str, str],
) -> None:
    """Verify PATCH /api/v1/context/progress updates reader state."""
    # First register the chapter
    report_payload = {
        "series_id": "mangadex:uuid-series-002",
        "series_title": "Chainsaw Man",
        "source_domain": "mangadex.org",
        "chapter_id": "chapter-csm-01",
        "chapter_ordinal": 1.0,
        "chapter_label": "Ch. 1",
        "chapter_url": "https://mangadex.org/chapter/csm-01/1",
        "total_pages": 5,
        "pages": [
            {"page_number": i, "image_url": f"https://cdn/csm{i}.jpg"} for i in range(1, 6)
        ],
    }
    await async_client.post(
        "/api/v1/context/report",
        json=report_payload,
        headers=client_headers,
    )

    # Update progress to page 3
    progress_payload = {
        "chapter_id": "chapter-csm-01",
        "page_number": 3,
    }
    resp = await async_client.patch(
        "/api/v1/context/progress",
        json=progress_payload,
        headers=client_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["chapter_id"] == "chapter-csm-01"
    assert data["last_read_page"] == 3
    assert data["status"] == "reading"

    # Update progress on non-existent chapter -> 404
    resp_404 = await async_client.patch(
        "/api/v1/context/progress",
        json={"chapter_id": "unknown-ch", "page_number": 1},
        headers=client_headers,
    )
    assert resp_404.status_code == 404
    err = resp_404.json()
    assert err["success"] is False
    assert err["error"]["code"] == "CHAPTER_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_chapter_pages_endpoint(
    async_client: httpx.AsyncClient,
    client_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/context/chapters/{chapter_id}/pages returns pages and statuses."""
    report_payload = {
        "series_id": "mangadex:uuid-series-003",
        "series_title": "One Piece",
        "source_domain": "mangadex.org",
        "chapter_id": "chapter-op-1000",
        "chapter_ordinal": 1000.0,
        "chapter_label": "Ch. 1000",
        "chapter_url": "https://mangadex.org/chapter/op-1000/1",
        "total_pages": 2,
        "pages": [
            {"page_number": 1, "image_url": "https://cdn/op1.jpg"},
            {"page_number": 2, "image_url": "https://cdn/op2.jpg"},
        ],
    }
    await async_client.post(
        "/api/v1/context/report",
        json=report_payload,
        headers=client_headers,
    )

    # Query chapter pages
    resp = await async_client.get(
        "/api/v1/context/chapters/chapter-op-1000/pages",
        headers=client_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["chapter_id"] == "chapter-op-1000"
    assert data["total_pages"] == 2
    assert len(data["pages"]) == 2
    assert data["pages"][0]["page_number"] == 1
    assert data["pages"][0]["status"] == "discovered"

    # Query non-existent chapter -> 404
    resp_404 = await async_client.get(
        "/api/v1/context/chapters/non-existent-ch/pages",
        headers=client_headers,
    )
    assert resp_404.status_code == 404
    assert resp_404.json()["error"]["code"] == "CHAPTER_NOT_FOUND"


@pytest.mark.asyncio
async def test_context_report_validation_errors(
    async_client: httpx.AsyncClient,
    client_headers: dict[str, str],
) -> None:
    """Verify 422 Unprocessable Entity on invalid request payloads."""
    # Invalid page number (<= 0)
    invalid_report = {
        "series_id": "mangadex:s",
        "series_title": "Title",
        "source_domain": "mangadex.org",
        "chapter_id": "ch",
        "chapter_ordinal": 1.0,
        "chapter_label": "1",
        "chapter_url": "https://url",
        "total_pages": 1,
        "pages": [
            {"page_number": 0, "image_url": "https://cdn/p0.jpg"},
        ],
    }
    resp = await async_client.post(
        "/api/v1/context/report",
        json=invalid_report,
        headers=client_headers,
    )
    assert resp.status_code == 422
