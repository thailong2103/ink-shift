"""Provider Registry managing swappable Cloud Vision LLM Providers."""

from __future__ import annotations

from src.backend.config import Settings
from src.backend.engines.cloud.provider import CloudProvider
from src.backend.logging import get_logger

logger = get_logger("cloud.registry")


class ProviderNotFoundError(KeyError):
    """Raised when a requested cloud provider is not registered."""


class ProviderRegistry:
    """Registry coordinating available cloud vision providers (Gemini, OpenAI/xKiro)."""

    def __init__(self, default_provider_name: str | None = None) -> None:
        settings = Settings()
        self._default_name = default_provider_name or getattr(settings, "inkshift_cloud_provider", "gemini")
        self._providers: dict[str, CloudProvider] = {}
        # Alias map for backwards compatibility / user convenience
        self._aliases: dict[str, str] = {
            "gemini": "google",
            "cloud-gemini": "google",
            "xkiro": "custom",
            "cloud-xkiro": "custom",
            "claude": "anthropic",
            "cloud-anthropic": "anthropic",
        }

    def register(self, name: str, provider: CloudProvider) -> None:
        """Register a provider instance under a canonical name."""
        key = name.strip().lower()
        self._providers[key] = provider
        logger.debug("Registered cloud provider: '%s' (%s)", key, provider.__class__.__name__)

    def register_alias(self, alias: str, target_name: str) -> None:
        """Register an alias pointing to a canonical provider name."""
        self._aliases[alias.strip().lower()] = target_name.strip().lower()

    def get(self, name: str | None = None) -> CloudProvider:
        """Retrieve a provider by name or return the configured default.

        Args:
            name: Provider name or alias ('google', 'gemini', 'openai', 'anthropic', 'custom', 'xkiro', etc.). If None, returns default.

        Returns:
            Registered CloudProvider instance.

        Raises:
            ProviderNotFoundError: If the requested provider or default is not registered.
        """
        raw_name = name if (name and name.strip()) else (self._default_name or "google")
        lookup_name = raw_name.strip().lower()

        # Check aliases first
        resolved_name = self._aliases.get(lookup_name, lookup_name)

        if resolved_name in self._providers:
            return self._providers[resolved_name]

        # If resolved name failed, try original
        if lookup_name in self._providers:
            return self._providers[lookup_name]

        # Backwards compatibility fallbacks for legacy tests
        if lookup_name in ("xkiro", "custom", "cloud-xkiro") and "openai" in self._providers:
            return self._providers["openai"]
        if lookup_name in ("gemini", "google", "cloud-gemini") and "gemini" in self._providers:
            return self._providers["gemini"]

        avail = ", ".join(sorted(self._providers.keys()))
        raise ProviderNotFoundError(
            f"Cloud provider '{lookup_name}' is not registered. Available: [{avail}]"
        )

    def list_providers(self) -> list[str]:
        """Return list of canonical registered provider names."""
        return sorted(self._providers.keys())

    async def is_available(self, name: str | None = None) -> bool:
        """Check whether the requested or default provider is available."""
        try:
            provider = self.get(name)
            return await provider.is_available()
        except ProviderNotFoundError:
            return False

    def __contains__(self, name: str) -> bool:
        key = name.strip().lower()
        return key in self._providers or key in self._aliases
