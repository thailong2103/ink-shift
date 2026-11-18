"""Aggregate router for v1 endpoints."""

from fastapi import APIRouter

from src.backend.api.v1.cache import router as cache_router
from src.backend.api.v1.context import router as context_router
from src.backend.api.v1.health import router as health_router
from src.backend.api.v1.models import router as models_router
from src.backend.api.v1.settings import router as settings_router
from src.backend.api.v1.telemetry import router as telemetry_router
from src.backend.api.v1.translate import router as translate_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(health_router, tags=["Health"])
v1_router.include_router(cache_router, tags=["Cache"])
v1_router.include_router(translate_router, tags=["Translate"])
v1_router.include_router(models_router)
v1_router.include_router(settings_router)
v1_router.include_router(context_router)
v1_router.include_router(telemetry_router)

__all__ = ["v1_router"]

