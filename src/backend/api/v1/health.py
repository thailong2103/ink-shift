"""Health check and engine availability discovery endpoint."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.backend.engines.registry import EngineNotFoundError

router = APIRouter()


class HealthResponse(BaseModel):
    """Health status and engine availability model."""

    status: Literal["ok"] = "ok"
    version: str = "0.1.0"
    engines_available: dict[str, bool] = Field(
        description="Map of registered engines to their operational readiness"
    )
    active_engine: str = Field(description="Currently active default engine identifier")


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return server health status, version, and registered translation engines."""
    registry = request.app.state.registry
    engines_available = await registry.list_available()

    try:
        active_engine = registry.get_default().name
    except EngineNotFoundError:
        active_engine = "none"


    return HealthResponse(
        status="ok",
        version="0.1.0",
        engines_available=engines_available,
        active_engine=active_engine,
    )
