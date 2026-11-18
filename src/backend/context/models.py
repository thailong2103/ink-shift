"""SQL DDL statements and database schema definitions for Manga Context Graph."""

from __future__ import annotations

CREATE_SERIES_TABLE = """
CREATE TABLE IF NOT EXISTS manga_series (
    series_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    source_domain   TEXT NOT NULL,
    cover_url       TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
"""

CREATE_CHAPTERS_TABLE = """
CREATE TABLE IF NOT EXISTS manga_chapters (
    chapter_id       TEXT PRIMARY KEY,
    series_id        TEXT NOT NULL REFERENCES manga_series(series_id) ON DELETE CASCADE,
    chapter_ordinal  REAL NOT NULL,
    chapter_label    TEXT NOT NULL,
    chapter_url      TEXT NOT NULL,
    total_pages      INTEGER DEFAULT 0,
    last_read_page   INTEGER DEFAULT 1,
    status           TEXT DEFAULT 'reading',
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);
"""

CREATE_PAGES_TABLE = """
CREATE TABLE IF NOT EXISTS chapter_pages (
    page_id          TEXT PRIMARY KEY,
    chapter_id       TEXT NOT NULL REFERENCES manga_chapters(chapter_id) ON DELETE CASCADE,
    page_number      INTEGER NOT NULL,
    image_url        TEXT NOT NULL,
    image_hash       TEXT,
    status           TEXT DEFAULT 'discovered',
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    CONSTRAINT uq_chapter_page UNIQUE (chapter_id, page_number)
);
"""

CREATE_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_chapters_series ON manga_chapters(series_id);",
    "CREATE INDEX IF NOT EXISTS idx_pages_chapter ON chapter_pages(chapter_id);",
    "CREATE INDEX IF NOT EXISTS idx_pages_hash ON chapter_pages(image_hash);",
]
