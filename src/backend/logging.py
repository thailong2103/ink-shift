"""Centralized structured logging, dual-handler telemetry, and stage tracing for InkShift."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from logging.handlers import RotatingFileHandler
from typing import Any

ROOT_LOGGER_NAME = "inkshift"
_LOGGING_INITIALIZED = False


def setup_logging(
    log_level: str = "WARNING",
    log_dir: str = "./data/logs",
    log_file_name: str = "inkshift.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Initialize dual-handler logging: clean console stream and rotating debug file.

    Args:
        log_level: Console log level ("DEBUG", "INFO", "WARNING", "ERROR").
        log_dir: Directory where log files are stored.
        log_file_name: Name of the rotating log file.
        max_bytes: Maximum byte size per log file before rotation (default 5MB).
        backup_count: Number of rotated log archives to retain.

    Returns:
        The configured root inkshift logger.
    """
    global _LOGGING_INITIALIZED

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    parsed_level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(logging.DEBUG)  # Root captures all, handlers filter

    # Avoid duplicate handlers on re-init
    if _LOGGING_INITIALIZED:
        return logger

    logger.handlers.clear()

    # 1. Console Stream Handler (Clean, high-level milestone logs for human view)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(parsed_level)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. Rotating File Handler (Granular debug telemetry, timings, and tracebacks)
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_path = os.path.join(log_dir, log_file_name)
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)-7s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except OSError as err:
        sys.stderr.write(f"[InkShift:Logging] Failed to initialize file logger at '{log_dir}': {err}\n")

    _LOGGING_INITIALIZED = True
    setup_extension_logging(log_dir=log_dir)
    return logger


EXTENSION_LOGGER_NAME = "inkshift.extension"
_EXTENSION_LOGGING_INITIALIZED = False


def setup_extension_logging(
    log_dir: str = "./data/logs",
    log_file_name: str = "extension.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Initialize dedicated RotatingFileHandler for browser extension telemetry.

    Extension logs are isolated to data/logs/extension.log and formatted with
    exact client millisecond timestamps.
    """
    global _EXTENSION_LOGGING_INITIALIZED

    logger = logging.getLogger(EXTENSION_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Keep extension logs isolated from root inkshift.log

    if _EXTENSION_LOGGING_INITIALIZED:
        return logger

    logger.handlers.clear()

    try:
        os.makedirs(log_dir, exist_ok=True)
        file_path = os.path.join(log_dir, log_file_name)
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter("%(message)s")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except OSError as err:
        sys.stderr.write(f"[InkShift:Logging] Failed to initialize extension file logger at '{log_dir}': {err}\n")

    _EXTENSION_LOGGING_INITIALIZED = True
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """Obtain a namespaced InkShift logger child instance.

    Args:
        name: Sub-namespace (e.g. 'local', 'detector', 'ocr', 'translator', 'api', 'extension.cs').

    Returns:
        Namespaced Logger instance.
    """
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def format_logfmt(event: str, **kwargs: Any) -> str:
    """Format structured event and key-value fields following the Logfmt standard.

    Example:
        format_logfmt("UpstreamDispatch", model="gemini-2.0-flash", bubbles=8)
        -> 'UpstreamDispatch: model="gemini-2.0-flash", bubbles=8'
    """
    parts: list[str] = []
    for k, v in kwargs.items():
        if v is None:
            formatted_v = "none"
        elif isinstance(v, bool):
            formatted_v = "true" if v else "false"
        elif isinstance(v, (int,)):
            formatted_v = str(v)
        elif isinstance(v, float):
            formatted_v = f"{v:.1f}" if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")
        else:
            s = str(v)
            if " " in s or '"' in s or "=" in s or "\n" in s:
                escaped = s.replace('"', '\\"').replace("\n", " ")
                formatted_v = f'"{escaped}"'
            else:
                formatted_v = s
        parts.append(f"{k}={formatted_v}")

    if parts:
        return f"{event}: {', '.join(parts)}"
    return event


class StageTracker:
    """State carrier for a tracked pipeline stage."""

    def __init__(self, stage_id: str, stage_name: str, logger: logging.Logger) -> None:
        self.stage_id = stage_id
        self.stage_name = stage_name
        self.logger = logger
        self.info: str | None = None
        self.elapsed_ms: float = 0.0


@asynccontextmanager
async def track_stage(
    stage_id: str,
    stage_name: str,
    logger: logging.Logger | None = None,
    extra_details: dict[str, Any] | None = None,
) -> AsyncGenerator[StageTracker, None]:
    """Async context manager measuring stage latency and capturing failure diagnostics in Logfmt format.

    Args:
        stage_id: Ordinal identifier (e.g. '1/5', '2/5').
        stage_name: Human-readable stage title.
        logger: Target logger instance (defaults to inkshift.local).
        extra_details: Optional metadata dictionary logged to debug stream.
    """
    log = logger or get_logger("local")
    tracker = StageTracker(stage_id, stage_name, log)

    log.info(format_logfmt("StageStarted", stage=stage_id, action=stage_name))
    if extra_details:
        log.debug(format_logfmt("StageContext", stage=stage_id, **extra_details))

    t0 = time.perf_counter()
    try:
        yield tracker
        tracker.elapsed_ms = (time.perf_counter() - t0) * 1000
        extra_kwargs: dict[str, Any] = {
            "stage": stage_id,
            "action": stage_name,
            "elapsed_ms": round(tracker.elapsed_ms, 1),
        }
        if tracker.info:
            extra_kwargs["details"] = tracker.info
        log.info(format_logfmt("StageCompleted", **extra_kwargs))
        log.debug(format_logfmt("StageTiming", stage=stage_id, action=stage_name, latency_ms=round(tracker.elapsed_ms, 2)))
    except Exception as exc:
        tracker.elapsed_ms = (time.perf_counter() - t0) * 1000
        log.exception(
            format_logfmt(
                "StageFailed",
                stage=stage_id,
                action=stage_name,
                elapsed_ms=round(tracker.elapsed_ms, 1),
                error_type=type(exc).__name__,
            )
        )
        raise


@contextmanager
def track_stage_sync(
    stage_id: str,
    stage_name: str,
    logger: logging.Logger | None = None,
    extra_details: dict[str, Any] | None = None,
) -> Generator[StageTracker, None, None]:
    """Synchronous context manager measuring stage latency and capturing failure diagnostics in Logfmt format."""
    log = logger or get_logger("local")
    tracker = StageTracker(stage_id, stage_name, log)

    log.info(format_logfmt("StageStarted", stage=stage_id, action=stage_name))
    if extra_details:
        log.debug(format_logfmt("StageContext", stage=stage_id, **extra_details))

    t0 = time.perf_counter()
    try:
        yield tracker
        tracker.elapsed_ms = (time.perf_counter() - t0) * 1000
        extra_kwargs: dict[str, Any] = {
            "stage": stage_id,
            "action": stage_name,
            "elapsed_ms": round(tracker.elapsed_ms, 1),
        }
        if tracker.info:
            extra_kwargs["details"] = tracker.info
        log.info(format_logfmt("StageCompleted", **extra_kwargs))
        log.debug(format_logfmt("StageTiming", stage=stage_id, action=stage_name, latency_ms=round(tracker.elapsed_ms, 2)))
    except Exception as exc:
        tracker.elapsed_ms = (time.perf_counter() - t0) * 1000
        log.exception(
            format_logfmt(
                "StageFailed",
                stage=stage_id,
                action=stage_name,
                elapsed_ms=round(tracker.elapsed_ms, 1),
                error_type=type(exc).__name__,
            )
        )
        raise
