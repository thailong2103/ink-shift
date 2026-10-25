"""Provider settings and API credentials management endpoints."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.backend.config import Settings
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.models import (
    ProviderSettingsResponse,
    ProviderStatus,
    UpdateProviderSettingsRequest,
)
from src.backend.security.env_manager import (
    atomic_write_env,
    get_provider_status,
    sync_runtime_settings,
)

logger = get_logger("api.settings")
router = APIRouter(prefix="/settings", tags=["Settings"])
ENV_PATH: str = ".env"


@router.get("/providers", response_model=ProviderSettingsResponse)
async def get_provider_settings(request: Request) -> ProviderSettingsResponse:
    """Retrieve masked configuration status for all 4 LLM providers."""
    settings: Settings = getattr(request.app.state, "settings", None) or Settings()
    status_dict = get_provider_status(settings)

    providers: dict[str, ProviderStatus] = {}
    for prov_name, st in status_dict.items():
        providers[prov_name] = ProviderStatus(
            configured=st.get("configured", False),
            masked_key=st.get("masked_key"),
            base_url=st.get("base_url"),
        )

    return ProviderSettingsResponse(success=True, providers=providers)


@router.post("/providers")
async def update_provider_settings(
    request: Request,
    payload: UpdateProviderSettingsRequest,
) -> dict[str, Any]:
    """Persist new API key or Base URL into host .env file and update runtime memory."""
    settings: Settings = getattr(request.app.state, "settings", None) or Settings()
    provider = payload.provider.strip().lower()

    updates: dict[str, str] = {}
    if provider == "google":
        if payload.api_key is not None:
            updates["GEMINI_API_KEY"] = payload.api_key.strip()
    elif provider == "openai":
        if payload.api_key is not None:
            updates["OPENAI_API_KEY"] = payload.api_key.strip()
        if payload.base_url is not None:
            updates["OPENAI_BASE_URL"] = payload.base_url.strip()
    elif provider == "anthropic":
        if payload.api_key is not None:
            updates["ANTHROPIC_API_KEY"] = payload.api_key.strip()
        if payload.base_url is not None:
            updates["ANTHROPIC_BASE_URL"] = payload.base_url.strip()
    elif provider == "custom":
        if payload.api_key is not None:
            clean_k = payload.api_key.strip()
            updates["CUSTOM_API_KEY"] = clean_k
            updates["XKIRO_API_KEY"] = clean_k
        if payload.base_url is not None:
            clean_url = payload.base_url.strip()
            updates["CUSTOM_BASE_URL"] = clean_url
            updates["XKIRO_BASE_URL"] = clean_url
    else:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PROVIDER", "message": f"Unsupported provider tier: {provider}"},
        )

    if not updates:
        return {"success": True, "message": "No changes requested", "provider": provider}

    # 1. Atomic file persist to .env
    env_path = os.environ.get("INKSHIFT_ENV_FILE", ENV_PATH)
    atomic_write_env(env_path, updates)

    # 2. Update memory Settings and os.environ immediately
    sync_runtime_settings(updates, settings)

    logger.info(
        format_logfmt(
            "ProviderSettingsUpdated",
            provider=provider,
            updated_keys=",".join(sorted(updates.keys())),
        )
    )

    refreshed_status = get_provider_status(settings).get(provider, {})
    return {
        "success": True,
        "provider": provider,
        "status": refreshed_status,
    }
