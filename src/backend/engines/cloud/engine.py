"""Composite Cloud Translation Engine implementing BaseTranslationEngine."""

from __future__ import annotations

import hashlib
import time

from src.backend.detection.base import DetectedBubble
from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.cloud.provider import CloudProvider
from src.backend.engines.cloud.provider_registry import ProviderRegistry
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.contract import (
    TranslationRequest,
    TranslationResponse,
)

logger = get_logger("cloud.engine")



class CloudTranslationEngine(BaseTranslationEngine):
    """Composite translation engine delegating to an active CloudProvider via ProviderRegistry."""

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        provider: CloudProvider | None = None,
        name: str = "cloud",
    ) -> None:
        self._name = name
        if registry is not None:
            self._registry = registry
        elif provider is not None:
            # Wrap standalone provider in a ProviderRegistry
            reg = ProviderRegistry(default_provider_name=provider.name)
            reg.register(provider.name, provider)
            self._registry = reg
        else:
            self._registry = ProviderRegistry()

    @property
    def name(self) -> str:
        """Engine identifier in the registry."""
        return self._name

    @property
    def registry(self) -> ProviderRegistry:
        """Configured ProviderRegistry instance."""
        return self._registry

    @property
    def provider(self) -> CloudProvider:
        """Configured default cloud vision provider instance."""
        return self._registry.get()

    async def is_available(self) -> bool:
        """Check whether underlying default provider is ready and configured."""
        try:
            return await self.provider.is_available()
        except KeyError:
            return False

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        """Translate manga page image using requested cloud vision provider and pre-detected bubbles.

        Strips any data URL prefix, resolves target provider, forwards payload with bubbles,
        and packages detected blocks into a contract-compliant TranslationResponse.
        """
        start_time = time.perf_counter()

        # 1. Determine canonical page hash
        if request.image_hash:
            page_hash = request.image_hash
        else:
            page_hash = hashlib.sha256(request.image.encode("utf-8")).hexdigest()

        # 2. Extract raw Base64 string from data URL prefix if present
        raw_b64 = request.image
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]

        # 3. Resolve active provider based on request.provider (falls back to default)
        target_provider = self._registry.get(request.provider)

        logger.info(
            format_logfmt(
                "CloudEngineDispatch",
                provider=target_provider.name,
                bubbles=len(bubbles) if bubbles else 0,
                target_lang=request.target_lang,
            )
        )

        # 4. Delegate Set-of-Marks manga localization to active provider
        blocks = await target_provider.translate_page(
            image_base64=raw_b64.strip(),
            target_lang=request.target_lang,
            model=request.model,
            bubbles=bubbles,
        )

        # 5. Measure execution latency and construct response
        latency_ms = max(0, int((time.perf_counter() - start_time) * 1000))
        logger.info(
            format_logfmt(
                "CloudEngineCompleted",
                provider=target_provider.name,
                blocks=len(blocks),
                latency_ms=latency_ms,
            )
        )
        return TranslationResponse(
            success=True,
            page_hash=page_hash,
            engine_used=self.name,
            execution_time_ms=latency_ms,
            from_cache=False,
            blocks=blocks,
        )
