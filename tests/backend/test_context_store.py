"""Unit tests for Manga Context Graph ContextStore and SQLite operations."""

from __future__ import annotations

import os
from pathlib import Path

import aiosqlite
import pytest

from src.backend.context.schemas import ChapterContextReport, PageItem
from src.backend.context.store import ContextStore


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    """Provide a path to a temporary test database file."""
    return str(tmp_path / "test_context.db")


@pytest.mark.asyncio
async def test_context_store_initialization(test_db_path: str) -> None:
    """Verify that tables and indices are properly created upon initialization."""
    store = ContextStore(db_path=test_db_path)
    await store.initialize()

    assert os.path.exists(test_db_path)

    async with aiosqlite.connect(test_db_path) as db, db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ) as cursor:
        tables = [row[0] for row in await cursor.fetchall()]

    assert "manga_series" in tables
    assert "manga_chapters" in tables
    assert "chapter_pages" in tables


@pytest.mark.asyncio
async def test_report_context_and_query(test_db_path: str) -> None:
    """Verify storing a full chapter manifest and querying chapter pages."""
    store = ContextStore(db_path=test_db_path)
    await store.initialize()

    report = ChapterContextReport(
        series_id="mangadex:series-123",
        series_title="Frieren: Beyond Journey's End",
        source_domain="mangadex.org",
        cover_url="https://uploads.mangadex.org/covers/123/cover.jpg",
        chapter_id="chapter-456",
        chapter_ordinal=102.5,
        chapter_label="Ch. 102.5",
        chapter_url="https://mangadex.org/chapter/456/1",
        total_pages=3,
        pages=[
            PageItem(page_number=1, image_url="https://cdn.example.com/p1.jpg"),
            PageItem(page_number=2, image_url="https://cdn.example.com/p2.jpg"),
            PageItem(page_number=3, image_url="https://cdn.example.com/p3.jpg"),
        ],
    )

    await store.report_context(report)

    details = await store.get_chapter_details("chapter-456")
    assert details is not None
    assert details.chapter_id == "chapter-456"
    assert details.total_pages == 3
    assert details.last_read_page == 1
    assert details.status == "reading"
    assert len(details.pages) == 3

    assert details.pages[0].page_number == 1
    assert details.pages[0].image_url == "https://cdn.example.com/p1.jpg"
    assert details.pages[0].status == "discovered"
    assert details.pages[2].page_number == 3


@pytest.mark.asyncio
async def test_report_context_idempotent_update(test_db_path: str) -> None:
    """Verify upserting chapter context multiple times updates cleanly without duplicates."""
    store = ContextStore(db_path=test_db_path)
    await store.initialize()

    report_v1 = ChapterContextReport(
        series_id="mangadex:series-abc",
        series_title="Initial Title",
        source_domain="mangadex.org",
        chapter_id="chapter-xyz",
        chapter_ordinal=1.0,
        chapter_label="Ch. 1",
        chapter_url="https://mangadex.org/chapter/xyz/1",
        total_pages=2,
        pages=[
            PageItem(page_number=1, image_url="https://cdn.example.com/p1.jpg"),
            PageItem(page_number=2, image_url="https://cdn.example.com/p2.jpg"),
        ],
    )
    await store.report_context(report_v1)

    # Simulate translation ready on page 1
    await store.update_page_status(
        chapter_id="chapter-xyz",
        page_number=1,
        status="ready",
        image_hash="abcde12345" * 6 + "abcd",
    )

    # Upsert updated title and same pages
    report_v2 = ChapterContextReport(
        series_id="mangadex:series-abc",
        series_title="Updated Canon Title",
        source_domain="mangadex.org",
        chapter_id="chapter-xyz",
        chapter_ordinal=1.0,
        chapter_label="Ch. 1 (Updated)",
        chapter_url="https://mangadex.org/chapter/xyz/1",
        total_pages=2,
        pages=[
            PageItem(page_number=1, image_url="https://cdn.example.com/p1_new.jpg"),
            PageItem(page_number=2, image_url="https://cdn.example.com/p2.jpg"),
        ],
    )
    await store.report_context(report_v2)

    details = await store.get_chapter_details("chapter-xyz")
    assert details is not None
    assert len(details.pages) == 2
    # Status should preserve 'ready' when re-reported
    assert details.pages[0].status == "ready"
    assert details.pages[0].image_url == "https://cdn.example.com/p1_new.jpg"
    assert details.pages[0].image_hash == "abcde12345" * 6 + "abcd"


@pytest.mark.asyncio
async def test_update_reading_progress(test_db_path: str) -> None:
    """Verify updating reading progress changes last_read_page and completion status."""
    store = ContextStore(db_path=test_db_path)
    await store.initialize()

    report = ChapterContextReport(
        series_id="mangadex:s1",
        series_title="Series 1",
        source_domain="mangadex.org",
        chapter_id="ch-progress",
        chapter_ordinal=5.0,
        chapter_label="Ch. 5",
        chapter_url="https://mangadex.org/chapter/ch-progress/1",
        total_pages=10,
        pages=[PageItem(page_number=i, image_url=f"http://cdn/{i}.jpg") for i in range(1, 11)],
    )
    await store.report_context(report)

    # Update to page 4
    updated = await store.update_reading_progress("ch-progress", 4)
    assert updated is True

    details = await store.get_chapter_details("ch-progress")
    assert details is not None
    assert details.last_read_page == 4
    assert details.status == "reading"

    # Update to final page 10 (should mark completed)
    updated = await store.update_reading_progress("ch-progress", 10)
    assert updated is True

    details = await store.get_chapter_details("ch-progress")
    assert details is not None
    assert details.last_read_page == 10
    assert details.status == "completed"

    # Non-existent chapter returns False
    res = await store.update_reading_progress("ch-non-existent", 2)
    assert res is False


@pytest.mark.asyncio
async def test_foreign_key_cascade_deletion(test_db_path: str) -> None:
    """Verify that deleting a manga series cascade deletes all child chapters and pages."""
    store = ContextStore(db_path=test_db_path)
    await store.initialize()

    report = ChapterContextReport(
        series_id="series-cascade",
        series_title="Cascade Test",
        source_domain="mangadex.org",
        chapter_id="chapter-cascade-1",
        chapter_ordinal=1.0,
        chapter_label="Ch. 1",
        chapter_url="https://mangadex.org/c1",
        total_pages=2,
        pages=[
            PageItem(page_number=1, image_url="https://cdn/1.jpg"),
            PageItem(page_number=2, image_url="https://cdn/2.jpg"),
        ],
    )
    await store.report_context(report)

    # Ensure records exist
    details = await store.get_chapter_details("chapter-cascade-1")
    assert details is not None
    pages = await store.get_chapter_pages("chapter-cascade-1")
    assert len(pages) == 2

    # Delete series
    deleted = await store.delete_series("series-cascade")
    assert deleted is True

    # Child chapter and pages must now be gone
    details_after = await store.get_chapter_details("chapter-cascade-1")
    assert details_after is None

    pages_after = await store.get_chapter_pages("chapter-cascade-1")
    assert len(pages_after) == 0
