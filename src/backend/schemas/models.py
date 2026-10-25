"""Schemas for dynamic model discovery and provider settings management."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelItem(BaseModel):
    """Metadata describing a single LLM model from provider catalogs."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique model identifier (e.g. 'gemini-2.5-flash', 'gpt-4o')")
    display_name: str = Field(description="Human-friendly label")
    supports_vision: bool = Field(description="Whether the model accepts image inputs")


class ModelDiscoveryRequest(BaseModel):
    """Payload to request live model catalog discovery for a provider tier."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["google", "openai", "anthropic", "custom"] = Field(
        description="Target provider tier ('google', 'openai', 'anthropic', 'custom')"
    )
    api_key_override: str | None = Field(
        default=None,
        description="Optional temporary API key override for probing prior to saving",
    )
    api_key: str | None = Field(
        default=None,
        description="Alias for api_key_override",
    )
    base_url_override: str | None = Field(
        default=None,
        description="Optional custom base URL override",
    )
    base_url: str | None = Field(
        default=None,
        description="Alias for base_url_override",
    )


class ModelDiscoveryResponse(BaseModel):
    """Standardized response containing live discovered models."""

    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = True
    provider: str
    models: list[ModelItem]


class ProviderStatus(BaseModel):
    """Configuration status and masked credential representation for a provider."""

    model_config = ConfigDict(extra="forbid")

    configured: bool = Field(description="Whether a valid key exists")
    masked_key: str | None = Field(
        default=None,
        description="Masked key representation, e.g. AIzaSy...4xK8",
    )
    base_url: str | None = Field(
        default=None,
        description="Configured base URL if applicable",
    )


class ProviderSettingsResponse(BaseModel):
    """Envelope returned by GET /api/v1/settings/providers."""

    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = True
    providers: dict[str, ProviderStatus]


class UpdateProviderSettingsRequest(BaseModel):
    """Payload sent to POST /api/v1/settings/providers to update API key or base URL."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["google", "openai", "anthropic", "custom"] = Field(
        description="Provider tier to update"
    )
    api_key: str | None = Field(
        default=None,
        description="New API key string to persist into .env",
    )
    base_url: str | None = Field(
        default=None,
        description="New Base URL to persist (primarily for custom provider)",
    )
