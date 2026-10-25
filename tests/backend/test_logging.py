"""Unit tests for Logfmt formatting and stage tracking."""

from __future__ import annotations

import logging

import pytest

from src.backend.logging import (
    format_logfmt,
    get_logger,
    track_stage,
    track_stage_sync,
)


def test_format_logfmt_simple() -> None:
    res = format_logfmt("RequestReceived", engine="cloud", status=200, is_cached=False)
    assert res == "RequestReceived: engine=cloud, status=200, is_cached=false"


def test_format_logfmt_escaping() -> None:
    res = format_logfmt("UpstreamError", message='Model "failed" unexpectedly', reason=None)
    assert res == 'UpstreamError: message="Model \\"failed\\" unexpectedly", reason=none'


def test_format_logfmt_no_args() -> None:
    res = format_logfmt("Ping")
    assert res == "Ping"


@pytest.mark.asyncio
async def test_track_stage_async_success(caplog: pytest.LogCaptureFixture) -> None:
    test_logger = get_logger("test.stage")
    with caplog.at_level(logging.INFO):
        async with track_stage("1/5", "DecodeImage", logger=test_logger) as stage:
            stage.info = "image=2000x3000"

    assert "StageStarted: stage=1/5, action=DecodeImage" in caplog.text
    assert "StageCompleted: stage=1/5, action=DecodeImage" in caplog.text
    assert 'details="image=2000x3000"' in caplog.text


@pytest.mark.asyncio
async def test_track_stage_async_failure(caplog: pytest.LogCaptureFixture) -> None:
    test_logger = get_logger("test.stage_fail")
    with caplog.at_level(logging.INFO), pytest.raises(ValueError, match="Corrupt payload"):
        async with track_stage("2/5", "ProcessCrop", logger=test_logger):
            raise ValueError("Corrupt payload")

    assert "StageStarted: stage=2/5, action=ProcessCrop" in caplog.text
    assert "StageFailed: stage=2/5, action=ProcessCrop" in caplog.text
    assert "error_type=ValueError" in caplog.text


def test_track_stage_sync_success(caplog: pytest.LogCaptureFixture) -> None:
    test_logger = get_logger("test.stage_sync")
    with caplog.at_level(logging.INFO), track_stage_sync("3/5", "SortOrder", logger=test_logger) as stage:
        stage.info = "items=5"

    assert "StageStarted: stage=3/5, action=SortOrder" in caplog.text
    assert "StageCompleted: stage=3/5, action=SortOrder" in caplog.text
    assert 'details="items=5"' in caplog.text


def test_setup_logging_millisecond_timestamp(tmp_path: pytest.TempPathFactory) -> None:
    import re
    from pathlib import Path

    import src.backend.logging as backend_logging

    backend_logging._LOGGING_INITIALIZED = False
    log_dir = str(tmp_path)
    logger = backend_logging.setup_logging(log_dir=log_dir, log_file_name="test_ms.log")
    logger.info("Test message with milliseconds")

    # Flush handlers
    for h in logger.handlers:
        h.flush()

    log_file = Path(log_dir) / "test_ms.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test message with milliseconds" in content
    # Assert timestamp pattern: YYYY-MM-DD HH:MM:SS.mmm
    match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.(\d{3})", content)
    assert match is not None, f"Expected millisecond timestamp in: {content}"


def test_setup_extension_logging(tmp_path: pytest.TempPathFactory) -> None:
    from pathlib import Path

    import src.backend.logging as backend_logging

    backend_logging._EXTENSION_LOGGING_INITIALIZED = False
    log_dir = str(tmp_path)
    ext_logger = backend_logging.setup_extension_logging(log_dir=log_dir, log_file_name="extension.log")
    ext_logger.info("2026-10-22 18:55:01.340 [INFO   ] [inkshift.extension.cs] Client log payload")

    for h in ext_logger.handlers:
        h.flush()

    ext_file = Path(log_dir) / "extension.log"
    assert ext_file.exists()
    content = ext_file.read_text(encoding="utf-8")
    assert "Client log payload" in content
