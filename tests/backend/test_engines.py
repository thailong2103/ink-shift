"""Unit tests for Pluggable Translation Engine Abstraction, Registry, and Mock Engine."""

import hashlib
import unittest
from typing import Any

from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.mock import MockTranslationEngine
from src.backend.engines.registry import EngineNotFoundError, EngineRegistry
from src.backend.schemas.contract import (
    TranslatedBlock,
    TranslationRequest,
    TranslationResponse,
)


class DummyEngine(BaseTranslationEngine):
    """Concrete engine implementation for registry tests."""

    def __init__(self, engine_name: str = "dummy", available: bool = True) -> None:
        self._name = engine_name
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return self._available

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: Any = None,
    ) -> TranslationResponse:
        page_hash = request.image_hash or hashlib.sha256(request.image.encode()).hexdigest()
        return TranslationResponse(
            page_hash=page_hash,
            engine_used=self.name,
            execution_time_ms=10,
            from_cache=False,
            blocks=[
                TranslatedBlock(
                    id="dummy_blk_1",
                    box=(100, 100, 200, 200),
                    source_text="テスト",
                    translated_text="Thử nghiệm",
                    direction="vertical",
                    confidence=0.95,
                )
            ],
        )


class TestBaseTranslationEngine(unittest.TestCase):
    """Verify Abstract Base Class enforcement."""

    def test_cannot_instantiate_abstract_base_class(self) -> None:
        """Instantiating BaseTranslationEngine directly must raise TypeError."""
        engine_cls: type[Any] = BaseTranslationEngine
        with self.assertRaises(TypeError):
            engine_cls()

    def test_incomplete_subclass_cannot_be_instantiated(self) -> None:
        """A subclass missing required abstract methods cannot be instantiated."""

        class IncompleteEngine(BaseTranslationEngine):
            @property
            def name(self) -> str:
                return "incomplete"

        incomplete_cls: type[Any] = IncompleteEngine
        with self.assertRaises(TypeError):
            incomplete_cls()


class TestEngineRegistry(unittest.IsolatedAsyncioTestCase):
    """Verify EngineRegistry registration, discovery, and fallback."""

    def setUp(self) -> None:
        self.registry = EngineRegistry()

    def test_register_and_get_engine(self) -> None:
        dummy = DummyEngine("custom-dummy")
        self.registry.register(dummy)

        retrieved = self.registry.get("custom-dummy")
        self.assertIs(retrieved, dummy)

    def test_get_non_existent_engine_raises_error(self) -> None:
        with self.assertRaises(EngineNotFoundError):
            self.registry.get("non-existent-engine")

    def test_set_and_get_default_engine(self) -> None:
        dummy1 = DummyEngine("engine-1")
        dummy2 = DummyEngine("engine-2")
        self.registry.register(dummy1)
        self.registry.register(dummy2, is_default=True)

        default_engine = self.registry.get_default()
        self.assertEqual(default_engine.name, "engine-2")

    def test_get_default_falls_back_to_first_registered_engine(self) -> None:
        dummy = DummyEngine("first-engine")
        self.registry.register(dummy)

        default_engine = self.registry.get_default()
        self.assertEqual(default_engine.name, "first-engine")

    def test_get_default_on_empty_registry_raises_error(self) -> None:
        with self.assertRaises(EngineNotFoundError):
            self.registry.get_default()

    async def test_list_available_engines(self) -> None:
        dummy_online = DummyEngine("online-engine", available=True)
        dummy_offline = DummyEngine("offline-engine", available=False)
        self.registry.register(dummy_online)
        self.registry.register(dummy_offline)

        available_map = await self.registry.list_available()
        self.assertEqual(available_map, {"online-engine": True, "offline-engine": False})


class TestMockTranslationEngine(unittest.IsolatedAsyncioTestCase):
    """Verify deterministic behavior and contract compliance of MockTranslationEngine."""

    def setUp(self) -> None:
        self.mock_engine = MockTranslationEngine()
        self.sample_hash = "c" * 64

    def test_mock_engine_metadata(self) -> None:
        self.assertEqual(self.mock_engine.name, "mock")

    async def test_mock_engine_is_always_available(self) -> None:
        self.assertTrue(await self.mock_engine.is_available())

    async def test_mock_engine_translation_with_explicit_hash(self) -> None:
        request = TranslationRequest(
            image="data:image/jpeg;base64,sample_payload",
            image_hash=self.sample_hash,
            target_lang="vi",
            engine="mock",
        )
        response = await self.mock_engine.translate(request)

        self.assertTrue(response.success)
        self.assertEqual(response.page_hash, self.sample_hash)
        self.assertEqual(response.engine_used, "mock")
        self.assertFalse(response.from_cache)
        self.assertGreaterEqual(response.execution_time_ms, 0)
        self.assertGreater(len(response.blocks), 0)

        for block in response.blocks:
            self.assertIsInstance(block.id, str)
            ymin, xmin, ymax, xmax = block.box
            self.assertGreaterEqual(ymin, 0)
            self.assertLessEqual(ymax, 1000)
            self.assertGreaterEqual(xmin, 0)
            self.assertLessEqual(xmax, 1000)
            self.assertLessEqual(ymin, ymax)
            self.assertLessEqual(xmin, xmax)
            self.assertTrue(len(block.translated_text) > 0)

    async def test_mock_engine_translation_computes_hash_if_missing(self) -> None:
        raw_image = "data:image/jpeg;base64,unique_mock_image_bytes"
        expected_hash = hashlib.sha256(raw_image.encode("utf-8")).hexdigest()

        request = TranslationRequest(
            image=raw_image,
            target_lang="vi",
            engine="mock",
        )
        response = await self.mock_engine.translate(request)

        self.assertEqual(response.page_hash, expected_hash)
        self.assertEqual(len(response.blocks), 3)


if __name__ == "__main__":
    unittest.main()
