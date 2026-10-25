"""Unit tests for FastAPI Telemetry batch ingestion endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import src.backend.logging as backend_logging
from src.backend.app import create_app
from src.backend.config import Settings


def test_post_telemetry_batch_success(tmp_path: Path) -> None:
    backend_logging._LOGGING_INITIALIZED = False
    backend_logging._EXTENSION_LOGGING_INITIALIZED = False

    log_dir = str(tmp_path)
    backend_logging.setup_logging(log_dir=log_dir)
    ext_logger = backend_logging.setup_extension_logging(log_dir=log_dir)

    app = create_app(Settings())
    client = TestClient(app)

    payload = {
        "logs": [
            {
                "timestamp_ms": 1729601701340.0,
                "level": "INFO",
                "module": "CS",
                "message": "Gui anh #0 toi background de dich",
                "trace_id": "trace-test-123",
                "extra": {"index": 0},
            },
            {
                "timestamp_ms": 1729601701450.0,
                "level": "WARNING",
                "module": "Prefetch",
                "message": "Tai truoc trang #2 that bai",
                "trace_id": "trace-test-456",
            },
        ]
    }

    headers = {"X-InkShift-Client": "extension"}
    resp = client.post("/api/v1/telemetry/logs", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] == 2

    # Flush extension logger
    for h in ext_logger.handlers:
        h.flush()

    ext_file = Path(log_dir) / "extension.log"
    assert ext_file.exists()
    content = ext_file.read_text(encoding="utf-8")

    assert "Gui anh #0 toi background de dich" in content
    assert "Tai truoc trang #2 that bai" in content
    assert "[trace-test-123]" in content
    assert "[inkshift.extension.cs]" in content
    assert "[inkshift.extension.prefetch]" in content


def test_post_telemetry_empty_batch(tmp_path: Path) -> None:
    backend_logging._LOGGING_INITIALIZED = False
    backend_logging._EXTENSION_LOGGING_INITIALIZED = False

    log_dir = str(tmp_path)
    backend_logging.setup_logging(log_dir=log_dir)

    app = create_app(Settings())
    client = TestClient(app)

    headers = {"X-InkShift-Client": "extension"}
    resp = client.post("/api/v1/telemetry/logs", json={"logs": []}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "count": 0}


def test_post_telemetry_validation_error() -> None:
    app = create_app(Settings())
    client = TestClient(app)

    headers = {"X-InkShift-Client": "extension"}
    # Missing message
    resp = client.post(
        "/api/v1/telemetry/logs",
        json={"logs": [{"timestamp_ms": 1729601701340.0, "level": "INFO", "module": "CS"}]},
        headers=headers,
    )
    assert resp.status_code == 422
