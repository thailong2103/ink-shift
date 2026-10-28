import os
import time

import aiosqlite

from src.backend.logging import get_logger
from src.backend.schemas.contract import TranslationResponse

logger = get_logger("cache")


class TranslationCache:
    """Async SQLite cache storing and retrieving translation responses with engine isolation."""

    def __init__(self, db_path: str = "./data/cache.db") -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Create parent directory if missing, apply migrations, and initialize schema with WAL mode."""
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")

            # Check if table already exists
            async with db.execute("PRAGMA table_info(translation_cache);") as cursor:
                cols = await cursor.fetchall()

            if cols:
                # Table exists; verify if translator_used column exists
                trans_col = [c for c in cols if c[1] == "translator_used"]
                if not trans_col:
                    logger.info("Migrating translation_cache to include translator_used in PRIMARY KEY")
                    await db.execute("ALTER TABLE translation_cache RENAME TO translation_cache_old;")
                    await db.execute(
                        """
                        CREATE TABLE translation_cache (
                            image_hash TEXT NOT NULL,
                            target_lang TEXT NOT NULL,
                            engine_used TEXT NOT NULL,
                            translator_used TEXT NOT NULL,
                            response_json TEXT NOT NULL,
                            created_at INTEGER NOT NULL,
                            PRIMARY KEY (image_hash, target_lang, engine_used, translator_used)
                        );
                        """
                    )
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO translation_cache 
                        (image_hash, target_lang, engine_used, translator_used, response_json, created_at)
                        SELECT image_hash, target_lang, engine_used, 'default', response_json, created_at 
                        FROM translation_cache_old;
                        """
                    )
                    await db.execute("DROP TABLE translation_cache_old;")
            else:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS translation_cache (
                        image_hash TEXT NOT NULL,
                        target_lang TEXT NOT NULL,
                        engine_used TEXT NOT NULL,
                        translator_used TEXT NOT NULL,
                        response_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY (image_hash, target_lang, engine_used, translator_used)
                    );
                    """
                )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cache_hash_lang_engine_trans 
                ON translation_cache(image_hash, target_lang, engine_used, translator_used);
                """
            )
            await db.commit()

    async def get_journal_mode(self) -> str:
        """Return the current SQLite journal mode (e.g. 'wal')."""
        async with (
            aiosqlite.connect(self.db_path) as db,
            db.execute("PRAGMA journal_mode;") as cursor,
        ):
            row = await cursor.fetchone()
            if row is not None and len(row) > 0:
                return str(row[0])
            return ""

    async def get(
        self,
        image_hash: str,
        target_lang: str,
        engine_used: str | None = None,
        translator_used: str | None = None,
    ) -> TranslationResponse | None:
        """Retrieve cached TranslationResponse by image_hash, target_lang, and optionally engine/translator.

        Returns None if not found in cache.
        """
        async with aiosqlite.connect(self.db_path) as db:
            if engine_used is not None and translator_used is not None:
                query = (
                    "SELECT response_json FROM translation_cache "
                    "WHERE image_hash = ? AND target_lang = ? AND engine_used = ? AND translator_used = ?;"
                )
                params: tuple[str, ...] = (image_hash, target_lang, engine_used, translator_used)
            elif engine_used is not None:
                query = (
                    "SELECT response_json FROM translation_cache "
                    "WHERE image_hash = ? AND target_lang = ? AND engine_used = ? "
                    "ORDER BY created_at DESC LIMIT 1;"
                )
                params = (image_hash, target_lang, engine_used)
            else:
                query = (
                    "SELECT response_json FROM translation_cache "
                    "WHERE image_hash = ? AND target_lang = ? "
                    "ORDER BY created_at DESC LIMIT 1;"
                )
                params = (image_hash, target_lang)

            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    logger.debug(
                        "Cache MISS for hash='%s' (target: %s, engine: %s, translator: %s)",
                        image_hash,
                        target_lang,
                        engine_used or "any",
                        translator_used or "any",
                    )
                    return None

                parsed = TranslationResponse.model_validate_json(row[0])
                logger.debug(
                    "Cache HIT for hash='%s' (target: %s, engine: %s, translator: %s, payload: %d bytes)",
                    image_hash,
                    target_lang,
                    parsed.engine_used,
                    translator_used or "any",
                    len(row[0]),
                )
                return parsed.model_copy(update={"from_cache": True})

    async def set(
        self,
        image_hash: str,
        target_lang: str,
        response: TranslationResponse,
        engine_used: str | None = None,
        translator_used: str | None = None,
    ) -> None:
        """Store or update a TranslationResponse in the cache."""
        resolved_engine = engine_used or response.engine_used
        resolved_translator = translator_used or "default"
        payload = response.model_dump_json()
        logger.debug(
            "Cache STORE for hash='%s' (target: %s, engine: %s, translator: %s, payload: %d bytes)",
            image_hash,
            target_lang,
            resolved_engine,
            resolved_translator,
            len(payload),
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO translation_cache 
                (image_hash, target_lang, engine_used, translator_used, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    image_hash,
                    target_lang,
                    resolved_engine,
                    resolved_translator,
                    payload,
                    int(time.time()),
                ),
            )
            await db.commit()

    async def delete(
        self,
        image_hash: str,
        target_lang: str | None = None,
        engine_used: str | None = None,
    ) -> int:
        """Delete specific cached translation entries matching criteria."""
        async with aiosqlite.connect(self.db_path) as db:
            conditions = ["image_hash = ?"]
            params: list[str] = [image_hash]
            if target_lang is not None:
                conditions.append("target_lang = ?")
                params.append(target_lang)
            if engine_used is not None:
                conditions.append("engine_used = ?")
                params.append(engine_used)

            query = f"DELETE FROM translation_cache WHERE {' AND '.join(conditions)};"
            cursor = await db.execute(query, tuple(params))
            deleted = cursor.rowcount
            await db.commit()
            logger.info("Deleted %d cache entries for hash %s", deleted, image_hash[:16])
            return deleted

    async def clear(self) -> int:
        """Clear all entries in translation cache, returning count of deleted records."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM translation_cache;") as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0

            await db.execute("DELETE FROM translation_cache;")
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            await db.commit()
            logger.info("Cleared entire translation cache (%d records deleted)", count)
            return count
