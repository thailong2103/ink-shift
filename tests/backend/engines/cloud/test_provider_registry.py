"""Unit tests for Cloud ProviderRegistry."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.backend.engines.cloud.provider import CloudProvider
from src.backend.engines.cloud.provider_registry import (
    ProviderNotFoundError,
    ProviderRegistry,
)


class TestProviderRegistry(unittest.IsolatedAsyncioTestCase):
    """Test suite for ProviderRegistry."""

    def setUp(self) -> None:
        self.registry = ProviderRegistry(default_provider_name="gemini")
        self.mock_gemini = MagicMock(spec=CloudProvider)
        self.mock_gemini.name = "gemini"
        self.mock_gemini.is_available = AsyncMock(return_value=True)

        self.mock_openai = MagicMock(spec=CloudProvider)
        self.mock_openai.name = "openai"
        self.mock_openai.is_available = AsyncMock(return_value=True)

    def test_register_and_get_canonical(self) -> None:
        self.registry.register("gemini", self.mock_gemini)
        self.registry.register("openai", self.mock_openai)

        self.assertIs(self.registry.get("gemini"), self.mock_gemini)
        self.assertIs(self.registry.get("openai"), self.mock_openai)
        self.assertIs(self.registry.get(None), self.mock_gemini)  # Default fallback
        self.assertIs(self.registry.get(""), self.mock_gemini)

    def test_alias_resolution(self) -> None:
        self.registry.register("gemini", self.mock_gemini)
        self.registry.register("openai", self.mock_openai)

        # "xkiro" should resolve to "openai"
        self.assertIs(self.registry.get("xkiro"), self.mock_openai)
        self.assertIs(self.registry.get("cloud-gemini"), self.mock_gemini)
        self.assertIs(self.registry.get("cloud-xkiro"), self.mock_openai)

    def test_unregistered_provider_raises_error(self) -> None:
        with self.assertRaises(ProviderNotFoundError):
            self.registry.get("anthropic")

    def test_list_providers(self) -> None:
        self.registry.register("gemini", self.mock_gemini)
        self.registry.register("openai", self.mock_openai)
        self.assertEqual(self.registry.list_providers(), ["gemini", "openai"])

    async def test_is_available(self) -> None:
        self.registry.register("gemini", self.mock_gemini)
        self.assertTrue(await self.registry.is_available("gemini"))
        self.assertFalse(await self.registry.is_available("anthropic"))


if __name__ == "__main__":
    unittest.main()
