"""Unit and lifespan integration tests for bounded idle ONNX model auto-unloading."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.backend.api.v1.translate import PriorityLocalLock
from src.backend.app import create_app, lifespan, maybe_unload_idle_local_models
from src.backend.config import Settings


class _StubLoadedDetector:
    """Minimal detector double tracking unload calls."""

    def __init__(self, last_used: float | None = None, loaded: bool = False) -> None:
        self.is_loaded = loaded
        self.last_used_monotonic = last_used
        self.unload_calls = 0

    def unload_session(self) -> bool:
        if not self.is_loaded:
            return False
        self.is_loaded = False
        self.last_used_monotonic = None
        self.unload_calls += 1
        return True


class _StubLoadedRapidOCR:
    """Minimal RapidOCR double tracking unload calls."""

    def __init__(self, last_used: float | None = None, loaded: bool = False) -> None:
        self.is_loaded = loaded
        self.last_used_monotonic = last_used
        self.unload_calls = 0

    def unload_sessions(self) -> bool:
        if not self.is_loaded:
            return False
        self.is_loaded = False
        self.last_used_monotonic = None
        self.unload_calls += 1
        return True


@pytest.mark.asyncio
async def test_maybe_unload_idle_respects_ttl_and_loaded_state() -> None:
    """Idle unload does nothing when disabled, unloaded, or below TTL, and unloads once expired."""
    lock = PriorityLocalLock()
    det = _StubLoadedDetector(last_used=100.0, loaded=True)
    ocr = _StubLoadedRapidOCR(last_used=100.0, loaded=True)

    # Disabled (<= 0)
    assert await maybe_unload_idle_local_models(det, ocr, lock, idle_ttl_seconds=0.0, now_monotonic=500.0) is False
    assert det.is_loaded is True and ocr.is_loaded is True

    # Before TTL expiry (elapsed = 50 < 180)
    assert await maybe_unload_idle_local_models(det, ocr, lock, idle_ttl_seconds=180.0, now_monotonic=150.0) is False
    assert det.is_loaded is True and ocr.is_loaded is True

    # Uses latest last_used across both components (ocr recently used at 250 -> only 30s elapsed)
    ocr.last_used_monotonic = 250.0
    assert await maybe_unload_idle_local_models(det, ocr, lock, idle_ttl_seconds=180.0, now_monotonic=280.0) is False
    assert det.is_loaded is True and ocr.is_loaded is True

    # Expired after TTL (250 + 180 = 430 <= 431)
    assert await maybe_unload_idle_local_models(det, ocr, lock, idle_ttl_seconds=180.0, now_monotonic=431.0) is True
    assert det.is_loaded is False and ocr.is_loaded is False
    assert det.unload_calls == 1 and ocr.unload_calls == 1

    # Already unloaded -> no-op returns False
    assert await maybe_unload_idle_local_models(det, ocr, lock, idle_ttl_seconds=180.0, now_monotonic=900.0) is False


@pytest.mark.asyncio
async def test_maybe_unload_idle_skips_when_local_lock_held() -> None:
    """Idle unload must never block or unload while PriorityLocalLock is held by inference."""
    lock = PriorityLocalLock()
    det = _StubLoadedDetector(last_used=10.0, loaded=True)
    ocr = _StubLoadedRapidOCR(last_used=10.0, loaded=True)

    async with lock.acquire_priority("P0"):
        unloaded = await maybe_unload_idle_local_models(
            det, ocr, lock, idle_ttl_seconds=60.0, now_monotonic=200.0
        )
        assert unloaded is False
        assert det.is_loaded is True and ocr.is_loaded is True

    # Once lock releases and still idle, unloading succeeds cleanly
    assert await maybe_unload_idle_local_models(det, ocr, lock, idle_ttl_seconds=60.0, now_monotonic=200.0) is True
    assert det.unload_calls == 1 and ocr.unload_calls == 1


@pytest.mark.asyncio
async def test_maybe_unload_idle_double_checks_timestamp_on_lock_acquisition() -> None:
    """Double-checked lock guard prevents unloading if activity refreshed timestamp before lock acquisition."""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    det = _StubLoadedDetector(last_used=10.0, loaded=True)
    ocr = _StubLoadedRapidOCR(last_used=10.0, loaded=True)

    class _TouchingPriorityLock(PriorityLocalLock):
        @asynccontextmanager
        async def acquire_priority(self, priority: str = "P0", key: str | None = None) -> AsyncIterator[None]:
            async with super().acquire_priority(priority, key=key):
                ocr.last_used_monotonic = 999.0
                yield

    lock = _TouchingPriorityLock()
    unloaded = await maybe_unload_idle_local_models(
        det, ocr, lock, idle_ttl_seconds=60.0, now_monotonic=1000.0
    )
    assert unloaded is False
    assert det.is_loaded is True and ocr.is_loaded is True


@pytest.mark.asyncio
async def test_lifespan_starts_idle_unload_watcher_and_cleans_up(tmp_path: Path) -> None:
    """FastAPI lifespan spawns idle watcher, unloads stale sessions, and cancels cleanly on exit."""
    import time

    settings = Settings(
        inkshift_db_path=str(tmp_path / "cache.db"),
        inkshift_default_engine="mock",
        inkshift_local_idle_unload_seconds=0.05,
    )
    app = create_app(settings)
    old_ts = time.monotonic() - 1.0
    det = _StubLoadedDetector(last_used=old_ts, loaded=True)
    ocr = _StubLoadedRapidOCR(last_used=old_ts, loaded=True)
    app.state.detector = det
    app.state.rapid_ocr = ocr

    task_ref: Any = None
    async with lifespan(app):
        task_ref = app.state.idle_unload_task
        assert task_ref is not None
        # Give watcher enough time to poll and trigger unload
        for _ in range(25):
            if not det.is_loaded and not ocr.is_loaded:
                break
            await asyncio.sleep(0.02)

        assert det.is_loaded is False
        assert ocr.is_loaded is False

    assert task_ref is not None
    assert task_ref.done() is True


@pytest.mark.asyncio
async def test_lifespan_disables_idle_watcher_when_zero(tmp_path: Path) -> None:
    """Setting INKSHIFT_LOCAL_IDLE_UNLOAD_SECONDS=0 skips spawning the background watcher task."""
    settings = Settings(
        inkshift_db_path=str(tmp_path / "cache_disabled.db"),
        inkshift_default_engine="mock",
        inkshift_local_idle_unload_seconds=0.0,
    )
    app = create_app(settings)
    det = _StubLoadedDetector(last_used=0.0, loaded=True)
    ocr = _StubLoadedRapidOCR(last_used=0.0, loaded=True)
    app.state.detector = det
    app.state.rapid_ocr = ocr

    async with lifespan(app):
        assert app.state.idle_unload_task is None

    # Shutdown still cleanly unloads any loaded native-like adapters via teardown helper
    assert det.unload_calls == 1
    assert ocr.unload_calls == 1
