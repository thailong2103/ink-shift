"""Unit tests for Backend Configuration and Async SQLite Cache Layer."""

import os
import shutil
import tempfile
import unittest

from src.backend.cache.sqlite_cache import TranslationCache
from src.backend.config import Settings
from src.backend.schemas.contract import TranslatedBlock, TranslationResponse


class TestBackendConfig(unittest.TestCase):
    """Test environment configuration parsing and defaults."""

    def test_default_settings(self) -> None:
        settings = Settings()
        self.assertEqual(settings.inkshift_db_path, "./data/cache.db")
        self.assertEqual(settings.inkshift_host, "127.0.0.1")
        self.assertEqual(settings.inkshift_port, 8000)
        self.assertEqual(settings.inkshift_default_engine, "mock")
        self.assertEqual(settings.max_payload_size, 20_000_000)

    def test_custom_environment_settings(self) -> None:
        os.environ["INKSHIFT_DB_PATH"] = "./custom_data/test.db"
        os.environ["INKSHIFT_HOST"] = "127.0.0.1"
        os.environ["INKSHIFT_PORT"] = "8080"
        os.environ["INKSHIFT_DEFAULT_ENGINE"] = "cloud"
        try:
            settings = Settings()
            self.assertEqual(settings.inkshift_db_path, "./custom_data/test.db")
            self.assertEqual(settings.inkshift_port, 8080)
            self.assertEqual(settings.inkshift_default_engine, "cloud")
        finally:
            del os.environ["INKSHIFT_DB_PATH"]
            del os.environ["INKSHIFT_HOST"]
            del os.environ["INKSHIFT_PORT"]
            del os.environ["INKSHIFT_DEFAULT_ENGINE"]


class TestTranslationCache(unittest.IsolatedAsyncioTestCase):
    """Test async SQLite translation caching."""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "nested", "test_cache.db")
        self.cache = TranslationCache(db_path=self.db_path)
        self.sample_hash = "a" * 64
        self.sample_response = TranslationResponse(
            page_hash=self.sample_hash,
            engine_used="mock-engine",
            execution_time_ms=120,
            from_cache=False,
            blocks=[
                TranslatedBlock(
                    id="blk_01",
                    box=(100, 200, 300, 400),
                    source_text="こんにちは",
                    translated_text="Xin chào",
                    direction="vertical",
                    confidence=0.99,
                )
            ],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_auto_creates_parent_directory_and_wal_mode(self) -> None:
        """Cache initialization must create non-existent directories and enable WAL mode."""
        nested_dir = os.path.dirname(self.db_path)
        self.assertFalse(os.path.exists(nested_dir))

        await self.cache.initialize()

        self.assertTrue(os.path.exists(nested_dir))
        self.assertTrue(os.path.exists(self.db_path))

        journal_mode = await self.cache.get_journal_mode()
        self.assertEqual(journal_mode.lower(), "wal")

    async def test_cache_miss_returns_none(self) -> None:
        """Querying a non-existent hash returns None."""
        await self.cache.initialize()
        result = await self.cache.get(image_hash="b" * 64, target_lang="vi")
        self.assertIsNone(result)

    async def test_cache_set_and_get_success(self) -> None:
        """Stored response is retrieved accurately with from_cache=True."""
        await self.cache.initialize()
        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=self.sample_response,
        )

        cached = await self.cache.get(image_hash=self.sample_hash, target_lang="vi")
        self.assertIsNotNone(cached)
        assert cached is not None  # Type narrow for mypy

        self.assertTrue(cached.from_cache)
        self.assertEqual(cached.page_hash, self.sample_hash)
        self.assertEqual(cached.engine_used, "mock-engine")
        self.assertEqual(len(cached.blocks), 1)
        self.assertEqual(cached.blocks[0].translated_text, "Xin chào")
        self.assertEqual(cached.blocks[0].box, (100, 200, 300, 400))

    async def test_cache_overwrite_updates_data(self) -> None:
        """Setting the same hash and lang replaces the existing entry."""
        await self.cache.initialize()
        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=self.sample_response,
        )

        updated_response = self.sample_response.model_copy(
            update={
                "blocks": [
                    TranslatedBlock(
                        id="blk_02",
                        box=(150, 250, 350, 450),
                        source_text="さようなら",
                        translated_text="Tạm biệt",
                        direction="vertical",
                        confidence=1.0,
                    )
                ]
            }
        )
        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=updated_response,
        )

        cached = await self.cache.get(image_hash=self.sample_hash, target_lang="vi")
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(len(cached.blocks), 1)
        self.assertEqual(cached.blocks[0].translated_text, "Tạm biệt")

    async def test_different_languages_cached_independently(self) -> None:
        """The same image hash can be cached separately for different target languages."""
        await self.cache.initialize()

        vi_response = self.sample_response
        en_response = self.sample_response.model_copy(
            update={
                "blocks": [
                    TranslatedBlock(
                        id="blk_en",
                        box=(100, 200, 300, 400),
                        source_text="こんにちは",
                        translated_text="Hello",
                        direction="vertical",
                        confidence=0.99,
                    )
                ]
            }
        )

        await self.cache.set(
            image_hash=self.sample_hash, target_lang="vi", response=vi_response
        )
        await self.cache.set(
            image_hash=self.sample_hash, target_lang="en", response=en_response
        )

        cached_vi = await self.cache.get(image_hash=self.sample_hash, target_lang="vi")
        cached_en = await self.cache.get(image_hash=self.sample_hash, target_lang="en")

        self.assertIsNotNone(cached_vi)
        self.assertIsNotNone(cached_en)
        assert cached_vi is not None
        assert cached_en is not None

        self.assertEqual(cached_vi.blocks[0].translated_text, "Xin chào")
        self.assertEqual(cached_en.blocks[0].translated_text, "Hello")

    async def test_different_engines_cached_independently(self) -> None:
        """The same image hash and lang are isolated per engine (no cross-engine collision)."""
        await self.cache.initialize()

        local_response = self.sample_response.model_copy(
            update={
                "engine_used": "local",
                "blocks": [
                    TranslatedBlock(
                        id="blk_loc",
                        box=(100, 200, 300, 400),
                        source_text="こんにちは",
                        translated_text="Chào từ Local Google",
                        direction="vertical",
                        confidence=0.95,
                    )
                ],
            }
        )
        cloud_response = self.sample_response.model_copy(
            update={
                "engine_used": "cloud",
                "blocks": [
                    TranslatedBlock(
                        id="blk_cld",
                        box=(100, 200, 300, 400),
                        source_text="こんにちは",
                        translated_text="Chào từ Cloud Gemini",
                        direction="vertical",
                        confidence=0.99,
                    )
                ],
            }
        )

        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=local_response,
            engine_used="local",
        )
        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=cloud_response,
            engine_used="cloud",
        )

        cached_local = await self.cache.get(
            image_hash=self.sample_hash, target_lang="vi", engine_used="local"
        )
        cached_cloud = await self.cache.get(
            image_hash=self.sample_hash, target_lang="vi", engine_used="cloud"
        )

        self.assertIsNotNone(cached_local)
        self.assertIsNotNone(cached_cloud)
        assert cached_local is not None
        assert cached_cloud is not None

        self.assertEqual(cached_local.engine_used, "local")
        self.assertEqual(cached_local.blocks[0].translated_text, "Chào từ Local Google")

        self.assertEqual(cached_cloud.engine_used, "cloud")
        self.assertEqual(cached_cloud.blocks[0].translated_text, "Chào từ Cloud Gemini")

    async def test_migration_from_legacy_primary_key(self) -> None:
        """Cache automatically migrates legacy schema to composite PRIMARY KEY with engine_used."""
        import aiosqlite

        nested_dir = os.path.dirname(self.db_path)
        os.makedirs(nested_dir, exist_ok=True)

        # Seed database with legacy schema
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE translation_cache (
                    image_hash TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    engine_used TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (image_hash, target_lang)
                );
                """
            )
            await db.execute(
                """
                INSERT INTO translation_cache VALUES (?, ?, ?, ?, ?);
                """,
                (
                    self.sample_hash,
                    "vi",
                    "legacy-engine",
                    self.sample_response.model_dump_json(),
                    1000,
                ),
            )
            await db.commit()

        # Run initialize() which triggers migration
        await self.cache.initialize()

        # Verify old row migrated and can now store a different engine for the same hash + lang
        migrated = await self.cache.get(
            image_hash=self.sample_hash, target_lang="vi", engine_used="legacy-engine"
        )
        self.assertIsNotNone(migrated)

        new_cloud = self.sample_response.model_copy(update={"engine_used": "cloud"})
        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=new_cloud,
            engine_used="cloud",
        )

        cached_legacy = await self.cache.get(
            image_hash=self.sample_hash, target_lang="vi", engine_used="legacy-engine"
        )
        cached_cloud = await self.cache.get(
            image_hash=self.sample_hash, target_lang="vi", engine_used="cloud"
        )
        self.assertIsNotNone(cached_legacy)
        self.assertIsNotNone(cached_cloud)
        assert cached_legacy is not None
        assert cached_cloud is not None
        self.assertEqual(cached_legacy.engine_used, "mock-engine")
        self.assertEqual(cached_cloud.engine_used, "cloud")

    async def test_multi_translator_isolation(self) -> None:
        """Cache must isolate entries with same image_hash and target_lang but different translators."""
        await self.cache.initialize()

        res_google = self.sample_response.model_copy(
            update={
                "blocks": [
                    TranslatedBlock(
                        id="b1",
                        box=(10, 10, 100, 100),
                        source_text="Hello",
                        translated_text="Xin chào (Google)",
                        direction="horizontal",
                        confidence=0.9,
                    )
                ]
            }
        )
        res_llm = self.sample_response.model_copy(
            update={
                "blocks": [
                    TranslatedBlock(
                        id="b1",
                        box=(10, 10, 100, 100),
                        source_text="Hello",
                        translated_text="Xin chào (LLM)",
                        direction="horizontal",
                        confidence=0.95,
                    )
                ]
            }
        )

        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=res_google,
            engine_used="local",
            translator_used="google-free",
        )
        await self.cache.set(
            image_hash=self.sample_hash,
            target_lang="vi",
            response=res_llm,
            engine_used="local",
            translator_used="llm-custom",
        )

        cached_google = await self.cache.get(
            image_hash=self.sample_hash,
            target_lang="vi",
            engine_used="local",
            translator_used="google-free",
        )
        cached_llm = await self.cache.get(
            image_hash=self.sample_hash,
            target_lang="vi",
            engine_used="local",
            translator_used="llm-custom",
        )

        self.assertIsNotNone(cached_google)
        self.assertIsNotNone(cached_llm)
        assert cached_google is not None
        assert cached_llm is not None
        self.assertEqual(cached_google.blocks[0].translated_text, "Xin chào (Google)")
        self.assertEqual(cached_llm.blocks[0].translated_text, "Xin chào (LLM)")

    async def test_cache_delete_and_clear(self) -> None:
        """Cache delete() and clear() must correctly remove entries and return counts."""
        await self.cache.initialize()

        hash_1 = "1" * 64
        hash_2 = "2" * 64

        await self.cache.set(
            image_hash=hash_1,
            target_lang="vi",
            response=self.sample_response,
            engine_used="local",
            translator_used="google-free",
        )
        await self.cache.set(
            image_hash=hash_2,
            target_lang="vi",
            response=self.sample_response,
            engine_used="local",
            translator_used="google-free",
        )

        deleted = await self.cache.delete(image_hash=hash_1)
        self.assertEqual(deleted, 1)

        self.assertIsNone(
            await self.cache.get(image_hash=hash_1, target_lang="vi", engine_used="local", translator_used="google-free")
        )
        self.assertIsNotNone(
            await self.cache.get(image_hash=hash_2, target_lang="vi", engine_used="local", translator_used="google-free")
        )

        cleared = await self.cache.clear()
        self.assertEqual(cleared, 1)
        self.assertIsNone(
            await self.cache.get(image_hash=hash_2, target_lang="vi", engine_used="local", translator_used="google-free")
        )


if __name__ == "__main__":
    unittest.main()

