import hashlib
import os
import sqlite3
import time

import aiosqlite

from src.backend.logging import get_logger
from src.backend.schemas.contract import TranslationResponse

logger = get_logger("cache")


def compute_prompt_hash(custom_prompt: str | None) -> str:
    """Return deterministic 16-hex hash of custom prompt, or empty string if None/whitespace."""
    if not custom_prompt or not custom_prompt.strip():
        return ""
    return hashlib.sha256(custom_prompt.strip().encode("utf-8")).hexdigest()[:16]


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
                # Table exists; verify if translator_used and prompt_hash columns exist
                col_names = {c[1] for c in cols}
                if "translator_used" not in col_names or "prompt_hash" not in col_names:
                    logger.info("Migrating translation_cache to include prompt_hash in PRIMARY KEY")
                    await db.execute("ALTER TABLE translation_cache RENAME TO translation_cache_old;")
                    await db.execute(
                        """
                        CREATE TABLE translation_cache (
                            image_hash TEXT NOT NULL,
                            target_lang TEXT NOT NULL,
                            engine_used TEXT NOT NULL,
                            translator_used TEXT NOT NULL,
                            prompt_hash TEXT NOT NULL DEFAULT '',
                            response_json TEXT NOT NULL,
                            created_at INTEGER NOT NULL,
                            PRIMARY KEY (image_hash, target_lang, engine_used, translator_used, prompt_hash)
                        );
                        """
                    )
                    trans_expr = "translator_used" if "translator_used" in col_names else "'default'"
                    prompt_expr = "prompt_hash" if "prompt_hash" in col_names else "''"
                    await db.execute(
                        f"""
                        INSERT OR IGNORE INTO translation_cache 
                        (image_hash, target_lang, engine_used, translator_used, prompt_hash, response_json, created_at)
                        SELECT image_hash, target_lang, engine_used, {trans_expr}, {prompt_expr}, response_json, created_at 
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
                        prompt_hash TEXT NOT NULL DEFAULT '',
                        response_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY (image_hash, target_lang, engine_used, translator_used, prompt_hash)
                    );
                    """
                )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cache_hash_lang_engine_trans_prompt 
                ON translation_cache(image_hash, target_lang, engine_used, translator_used, prompt_hash);
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
        prompt_hash: str | None = None,
    ) -> TranslationResponse | None:
        """Retrieve cached TranslationResponse by image_hash, target_lang, and optionally engine/translator/prompt_hash.

        Returns None if not found in cache.
        """
        async with aiosqlite.connect(self.db_path) as db:
            resolved_prompt = prompt_hash if prompt_hash is not None else ""
            if engine_used is not None and translator_used is not None:
                query = (
                    "SELECT response_json FROM translation_cache "
                    "WHERE image_hash = ? AND target_lang = ? AND engine_used = ? AND translator_used = ? AND prompt_hash = ?;"
                )
                params: tuple[str, ...] = (image_hash, target_lang, engine_used, translator_used, resolved_prompt)
            elif engine_used is not None:
                query = (
                    "SELECT response_json FROM translation_cache "
                    "WHERE image_hash = ? AND target_lang = ? AND engine_used = ? AND prompt_hash = ? "
                    "ORDER BY created_at DESC LIMIT 1;"
                )
                params = (image_hash, target_lang, engine_used, resolved_prompt)
            else:
                query = (
                    "SELECT response_json FROM translation_cache "
                    "WHERE image_hash = ? AND target_lang = ? AND prompt_hash = ? "
                    "ORDER BY created_at DESC LIMIT 1;"
                )
                params = (image_hash, target_lang, resolved_prompt)

            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    logger.debug(
                        "Cache MISS for hash='%s' (target: %s, engine: %s, translator: %s, prompt_hash: %s)",
                        image_hash,
                        target_lang,
                        engine_used or "any",
                        translator_used or "any",
                        resolved_prompt or "none",
                    )
                    return None

                parsed = TranslationResponse.model_validate_json(row[0])
                logger.debug(
                    "Cache HIT for hash='%s' (target: %s, engine: %s, translator: %s, prompt_hash: %s, payload: %d bytes)",
                    image_hash,
                    target_lang,
                    parsed.engine_used,
                    translator_used or "any",
                    resolved_prompt or "none",
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
        prompt_hash: str | None = None,
    ) -> None:
        """Store or update a TranslationResponse in the cache."""
        resolved_engine = engine_used or response.engine_used
        resolved_translator = translator_used or "default"
        resolved_prompt = prompt_hash or ""
        payload = response.model_dump_json()
        logger.debug(
            "Cache STORE for hash='%s' (target: %s, engine: %s, translator: %s, prompt_hash: %s, payload: %d bytes)",
            image_hash,
            target_lang,
            resolved_engine,
            resolved_translator,
            resolved_prompt,
            len(payload),
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO translation_cache 
                (image_hash, target_lang, engine_used, translator_used, prompt_hash, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    image_hash,
                    target_lang,
                    resolved_engine,
                    resolved_translator,
                    resolved_prompt,
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
            await db.commit()
            try:
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except (aiosqlite.Error, sqlite3.Error) as e:
                logger.warning("WAL checkpoint after cache clear skipped or failed: %s", e)
            logger.info("Cleared entire translation cache (%d records deleted)", count)
            return count
