"""Asynchronous SQLite storage implementation for Manga Context Graph."""

from __future__ import annotations

import os
import time
from typing import cast

import aiosqlite

from src.backend.context.models import (
    CREATE_CHAPTERS_TABLE,
    CREATE_INDICES,
    CREATE_PAGES_TABLE,
    CREATE_SERIES_TABLE,
)
from src.backend.context.schemas import (
    ChapterContextReport,
    ChapterPagesResponse,
    ChapterStatus,
    PageResponse,
    PageStatus,
)
from src.backend.logging import format_logfmt, get_logger

logger = get_logger("context.store")


class ContextStore:
    """Manages SQLite tables for series, chapters, and pages with WAL mode and foreign key cascades."""

    def __init__(self, db_path: str = "./data/cache.db") -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Create parent directory if missing and initialize Context Graph schema."""
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA synchronous = NORMAL;")

            await db.execute(CREATE_SERIES_TABLE)
            await db.execute(CREATE_CHAPTERS_TABLE)
            await db.execute(CREATE_PAGES_TABLE)

            for index_sql in CREATE_INDICES:
                await db.execute(index_sql)

            await db.commit()
            logger.info(format_logfmt("ContextStoreInitialized", wal_mode=True, foreign_keys=True))

    async def report_context(self, report: ChapterContextReport) -> None:
        """Atomically upsert series, chapter, and page manifest in a single transaction."""
        now = int(time.time())
        total_p = report.total_pages or len(report.pages)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("BEGIN TRANSACTION;")

            # 1. Upsert Series
            await db.execute(
                """
                INSERT INTO manga_series (series_id, title, source_domain, cover_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id) DO UPDATE SET
                    title = excluded.title,
                    source_domain = excluded.source_domain,
                    cover_url = COALESCE(excluded.cover_url, manga_series.cover_url),
                    updated_at = excluded.updated_at;
                """,
                (
                    report.series_id,
                    report.series_title,
                    report.source_domain,
                    report.cover_url,
                    now,
                    now,
                ),
            )

            # 2. Upsert Chapter
            await db.execute(
                """
                INSERT INTO manga_chapters (
                    chapter_id, series_id, chapter_ordinal, chapter_label,
                    chapter_url, total_pages, last_read_page, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, 'reading', ?, ?)
                ON CONFLICT(chapter_id) DO UPDATE SET
                    chapter_ordinal = excluded.chapter_ordinal,
                    chapter_label = excluded.chapter_label,
                    chapter_url = excluded.chapter_url,
                    total_pages = CASE WHEN excluded.total_pages > 0 THEN excluded.total_pages ELSE manga_chapters.total_pages END,
                    updated_at = excluded.updated_at;
                """,
                (
                    report.chapter_id,
                    report.series_id,
                    report.chapter_ordinal,
                    report.chapter_label,
                    report.chapter_url,
                    total_p,
                    now,
                    now,
                ),
            )

            # 3. Upsert Pages
            for page in report.pages:
                page_id = f"{report.chapter_id}#p-{page.page_number}"
                await db.execute(
                    """
                    INSERT INTO chapter_pages (
                        page_id, chapter_id, page_number, image_url, image_hash, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chapter_id, page_number) DO UPDATE SET
                        image_url = excluded.image_url,
                        image_hash = COALESCE(excluded.image_hash, chapter_pages.image_hash),
                        status = CASE WHEN chapter_pages.status = 'ready' THEN 'ready' ELSE excluded.status END,
                        updated_at = excluded.updated_at;
                    """,
                    (
                        page_id,
                        report.chapter_id,
                        page.page_number,
                        page.image_url,
                        page.image_hash,
                        page.status,
                        now,
                        now,
                    ),
                )

            await db.commit()

    async def update_reading_progress(self, chapter_id: str, page_number: int) -> bool:
        """Update last_read_page for chapter, marking completed if target page >= total_pages."""
        now = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute(
                """
                UPDATE manga_chapters
                SET last_read_page = ?,
                    status = CASE WHEN ? >= total_pages AND total_pages > 0 THEN 'completed' ELSE 'reading' END,
                    updated_at = ?
                WHERE chapter_id = ?;
                """,
                (page_number, page_number, now, chapter_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_page_status(
        self,
        chapter_id: str,
        page_number: int,
        status: PageStatus,
        image_hash: str | None = None,
    ) -> bool:
        """Update status and optional image_hash for a specific page."""
        now = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute(
                """
                UPDATE chapter_pages
                SET status = ?,
                    image_hash = COALESCE(?, image_hash),
                    updated_at = ?
                WHERE chapter_id = ? AND page_number = ?;
                """,
                (status, image_hash, now, chapter_id, page_number),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_chapter_pages(self, chapter_id: str) -> list[PageResponse]:
        """Fetch all pages for a chapter ordered by page_number."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            async with db.execute(
                """
                SELECT page_id, chapter_id, page_number, image_url, image_hash, status, created_at, updated_at
                FROM chapter_pages
                WHERE chapter_id = ?
                ORDER BY page_number ASC;
                """,
                (chapter_id,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [
            PageResponse(
                page_id=row[0],
                chapter_id=row[1],
                page_number=row[2],
                image_url=row[3],
                image_hash=row[4],
                status=cast(PageStatus, row[5]),
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    async def get_chapter_details(self, chapter_id: str) -> ChapterPagesResponse | None:
        """Fetch chapter summary along with its ordered pages."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            async with db.execute(
                """
                SELECT chapter_id, total_pages, last_read_page, status
                FROM manga_chapters
                WHERE chapter_id = ?;
                """,
                (chapter_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                return None

            pages = await self.get_chapter_pages(chapter_id)

            return ChapterPagesResponse(
                chapter_id=row[0],
                total_pages=row[1],
                last_read_page=row[2],
                status=cast(ChapterStatus, row[3]),
                pages=pages,
            )

    async def delete_series(self, series_id: str) -> bool:
        """Delete series and cascade delete all associated chapters and pages."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cursor = await db.execute(
                "DELETE FROM manga_series WHERE series_id = ?;",
                (series_id,),
            )
            await db.commit()
            return cursor.rowcount > 0
