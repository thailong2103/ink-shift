"""Dynamic live model discovery router proxying upstream provider catalogs."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException, Request

from src.backend.config import Settings
from src.backend.logging import get_logger
from src.backend.schemas.contract import APIErrorResponse
from src.backend.schemas.models import (
    ModelDiscoveryRequest,
    ModelDiscoveryResponse,
    ModelItem,
)

logger = get_logger("api.models")
router = APIRouter(prefix="/models", tags=["Models"])


def _classify_vision_openai(model_id: str) -> bool:
    """Classify whether an OpenAI model ID supports vision/multimodal input."""
    lower = model_id.lower()
    if "o1-mini" in lower or "o1-preview" in lower:
        return False
    vision_signatures = ["4o", "4-turbo", "vision", "o1", "gpt-4.5"]
    return any(sig in lower for sig in vision_signatures)


def _classify_vision_custom(model_id: str) -> bool:
    """Classify whether a third-party or local OpenAI-compatible model supports vision."""
    lower = model_id.lower()
    vision_signatures = [
        "vl",
        "vision",
        "multimodal",
        "4o",
        "gemini",
        "claude",
        "pixtral",
        "internvl",
        "minicpm",
        "qwen2.5-vl",
        "llava",
    ]
    return any(sig in lower for sig in vision_signatures)


@router.post(
    "/discover",
    response_model=ModelDiscoveryResponse,
    responses={
        200: {"model": ModelDiscoveryResponse, "description": "Models discovered successfully"},
        401: {"model": APIErrorResponse, "description": "Missing or invalid API credentials"},
        502: {"model": APIErrorResponse, "description": "Upstream catalog query failed"},
        504: {"model": APIErrorResponse, "description": "Upstream catalog request timed out"},
    },
)
async def discover_models(
    request: Request,
    payload: ModelDiscoveryRequest,
) -> ModelDiscoveryResponse:
    """Query upstream provider catalog live and return formatted list with vision tagging."""
    settings: Settings = getattr(request.app.state, "settings", None) or Settings()
    client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        own_client = True

    try:
        return await _discover_provider_models(payload, settings, client)
    finally:
        if own_client:
            await client.aclose()


async def _discover_provider_models(
    payload: ModelDiscoveryRequest,
    settings: Settings,
    client: httpx.AsyncClient,
) -> ModelDiscoveryResponse:
    provider = payload.provider.strip().lower()

    # 1. Google Gemini
    if provider == "google":
        key = (
            payload.api_key_override
            or payload.api_key
            or (settings.gemini_api_key if settings.gemini_api_key else "")
            or os.getenv("GEMINI_API_KEY", "")
        )
        if not key or not key.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "MISSING_API_KEY", "message": "Google Gemini API key is not configured."},
            )

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models?key={key.strip()}"
        try:
            resp = await client.get(endpoint, timeout=10.0)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "UPSTREAM_TIMEOUT", "message": "Google AI Studio models query timed out."},
            ) from exc
        except httpx.NetworkError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Network error contacting Google: {exc}"},
            ) from exc

        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_API_KEY", "message": "Google Gemini API key is invalid or unauthorized."},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Google returned HTTP {resp.status_code}: {resp.text}"},
            )

        data = resp.json()
        raw_models = data.get("models", [])
        items: list[ModelItem] = []
        for m in raw_models:
            raw_name = m.get("name", "")
            model_id = raw_name.split("/")[-1] if "/" in raw_name else raw_name
            display_name = m.get("displayName") or model_id
            methods = m.get("supportedGenerationMethods", [])

            # Only include models that generate content (chat/multimodal); skip embeddings and QA
            if "generateContent" not in methods:
                continue
            if model_id.startswith(("text-embedding", "aqa")):
                continue

            items.append(
                ModelItem(
                    id=model_id,
                    display_name=display_name,
                    supports_vision=True,  # Modern Gemini generateContent models support vision
                )
            )

        # Sort: newest Gemini models first
        items.sort(key=lambda x: ("2.5" not in x.id, "2.0" not in x.id, "1.5" not in x.id, x.id))
        return ModelDiscoveryResponse(success=True, provider="google", models=items)

    # 2. OpenAI Official
    if provider == "openai":
        key = (
            payload.api_key_override
            or payload.api_key
            or (settings.openai_api_key if settings.openai_api_key else "")
            or os.getenv("OPENAI_API_KEY", "")
        )
        base_url = str(
            payload.base_url_override
            or payload.base_url
            or (settings.openai_base_url if settings.openai_base_url else "")
            or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")

        if not key or not key.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "MISSING_API_KEY", "message": "OpenAI API key is not configured."},
            )

        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {key.strip()}"}
        try:
            resp = await client.get(endpoint, headers=headers, timeout=10.0)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "UPSTREAM_TIMEOUT", "message": "OpenAI models query timed out."},
            ) from exc
        except httpx.NetworkError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Network error contacting OpenAI: {exc}"},
            ) from exc

        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_API_KEY", "message": "OpenAI API key is invalid or unauthorized."},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"OpenAI returned HTTP {resp.status_code}: {resp.text}"},
            )

        data = resp.json()
        raw_list = data.get("data", [])
        items = []
        excluded_patterns = [
            "embedding",
            "tts",
            "whisper",
            "dall-e",
            "moderation",
            "babbage",
            "davinci",
            "text-curie",
            "canary",
            "realtime",
        ]
        for m in raw_list:
            m_id = m.get("id", "")
            if any(p in m_id.lower() for p in excluded_patterns):
                continue
            items.append(
                ModelItem(
                    id=m_id,
                    display_name=m_id,
                    supports_vision=_classify_vision_openai(m_id),
                )
            )

        # Sort: 4o, 4-turbo, o1 first
        items.sort(key=lambda x: (not x.supports_vision, "4o" not in x.id, x.id))
        return ModelDiscoveryResponse(success=True, provider="openai", models=items)

    # 3. Anthropic Claude
    if provider == "anthropic":
        key = (
            payload.api_key_override
            or payload.api_key
            or (settings.anthropic_api_key if settings.anthropic_api_key else "")
            or os.getenv("ANTHROPIC_API_KEY", "")
        )
        base_url = str(
            payload.base_url_override
            or payload.base_url
            or (settings.anthropic_base_url if settings.anthropic_base_url else "")
            or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        ).rstrip("/")

        if not key or not key.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "MISSING_API_KEY", "message": "Anthropic API key is not configured."},
            )

        endpoint = f"{base_url}/models"
        headers = {
            "x-api-key": key.strip(),
            "anthropic-version": "2023-06-01",
        }
        try:
            resp = await client.get(endpoint, headers=headers, timeout=10.0)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "UPSTREAM_TIMEOUT", "message": "Anthropic models query timed out."},
            ) from exc
        except httpx.NetworkError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Network error contacting Anthropic: {exc}"},
            ) from exc

        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_API_KEY", "message": "Anthropic API key is invalid or unauthorized."},
            )
        if resp.status_code == 404:
            # Fallback catalog when /v1/models endpoint is not available
            fallback_models = [
                ModelItem(id="claude-3-5-sonnet-20241022", display_name="Claude 3.5 Sonnet", supports_vision=True),
                ModelItem(id="claude-3-5-haiku-20241022", display_name="Claude 3.5 Haiku", supports_vision=True),
                ModelItem(id="claude-3-opus-20240229", display_name="Claude 3 Opus", supports_vision=True),
            ]
            return ModelDiscoveryResponse(success=True, provider="anthropic", models=fallback_models)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Anthropic returned HTTP {resp.status_code}: {resp.text}"},
            )

        data = resp.json()
        raw_list = data.get("data", [])
        items = []
        for m in raw_list:
            m_id = m.get("id", "")
            display_name = m.get("display_name") or m_id
            items.append(
                ModelItem(
                    id=m_id,
                    display_name=display_name,
                    supports_vision=m_id.startswith("claude-3"),
                )
            )

        items.sort(key=lambda x: ("3-5" not in x.id, "sonnet" not in x.id, x.id))
        return ModelDiscoveryResponse(success=True, provider="anthropic", models=items)

    # 4. Custom OpenAI-Compatible
    if provider == "custom":
        key = (
            payload.api_key_override
            or payload.api_key
            or (settings.custom_api_key if settings.custom_api_key else "")
            or getattr(settings, "xkiro_api_key", "")
            or os.getenv("CUSTOM_API_KEY", "")
            or os.getenv("XKIRO_API_KEY", "")
        )
        base_url = str(
            payload.base_url_override
            or payload.base_url
            or (settings.custom_base_url if settings.custom_base_url else "")
            or getattr(settings, "xkiro_base_url", "")
            or os.getenv("CUSTOM_BASE_URL", "")
            or os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1")
        ).rstrip("/")

        endpoint = f"{base_url}/models"
        headers = {}
        if key and key.strip():
            headers["Authorization"] = f"Bearer {key.strip()}"

        try:
            resp = await client.get(endpoint, headers=headers, timeout=10.0)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "UPSTREAM_TIMEOUT", "message": f"Custom endpoint models query timed out: {base_url}"},
            ) from exc
        except httpx.NetworkError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Network error contacting custom endpoint: {exc}"},
            ) from exc

        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_API_KEY", "message": "Custom endpoint rejected authorization credentials."},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"code": "UPSTREAM_CATALOG_ERROR", "message": f"Custom endpoint returned HTTP {resp.status_code}: {resp.text}"},
            )

        data = resp.json()
        raw_list = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        items = []
        for m in raw_list:
            m_id = m.get("id", "") if isinstance(m, dict) else str(m)
            if not m_id:
                continue
            items.append(
                ModelItem(
                    id=m_id,
                    display_name=m_id,
                    supports_vision=_classify_vision_custom(m_id),
                )
            )

        items.sort(key=lambda x: (not x.supports_vision, x.id))
        return ModelDiscoveryResponse(success=True, provider="custom", models=items)

    raise HTTPException(status_code=400, detail={"code": "INVALID_PROVIDER", "message": f"Unknown provider tier: {provider}"})
