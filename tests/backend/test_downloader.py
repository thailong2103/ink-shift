"""Unit tests for automated model weights downloader (src.backend.detection.downloader)."""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path
from typing import Self
from unittest.mock import patch

import pytest

from src.backend.detection.downloader import (
    ensure_model_file,
    ensure_ocr_model_files,
    format_bytes,
)


def test_format_bytes() -> None:
    """Format bytes calculates accurate MB representation."""
    assert format_bytes(1024 * 1024) == "1.0 MB"
    assert format_bytes(39_300_000) == "37.5 MB"


def test_ensure_model_file_skips_when_already_exists(tmp_path: Path) -> None:
    """If model file already exists and meets min_size, skip download."""
    model_file = tmp_path / "model.onnx"
    # Create dummy file with sufficient size
    dummy_bytes = b"X" * 1000
    model_file.write_bytes(dummy_bytes)

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = ensure_model_file(
            dest_path=model_file,
            min_size=500,
            show_progress=False,
        )
        assert result == model_file
        mock_urlopen.assert_not_called()


class MockHttpResponse:
    """Mock for urllib.request.urlopen response context manager."""

    def __init__(self, data: bytes) -> None:
        self._bio = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, chunk_size: int = -1) -> bytes:
        return self._bio.read(chunk_size)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass


def test_ensure_model_file_downloads_when_missing(tmp_path: Path) -> None:
    """If model file is missing, stream download chunks and atomically rename."""
    model_file = tmp_path / "model.onnx"
    assert not model_file.exists()

    payload = b"YOLO_MODEL_DATA_CHUNK_" * 50  # 1100 bytes
    mock_resp = MockHttpResponse(payload)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = ensure_model_file(
            dest_path=model_file,
            min_size=1000,
            show_progress=False,
        )
        assert result == model_file
        assert model_file.exists()
        assert model_file.read_bytes() == payload
        # Ensure temporary file was removed
        assert not model_file.with_suffix(".onnx.tmp").exists()


def test_ensure_model_file_redownloads_when_undersized(tmp_path: Path) -> None:
    """If existing model file is smaller than min_size, re-download."""
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"CORRUPTED_SHORT_DATA")

    full_payload = b"FULL_VALID_MODEL_PAYLOAD_" * 100  # 2600 bytes
    mock_resp = MockHttpResponse(full_payload)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = ensure_model_file(
            dest_path=model_file,
            min_size=2000,
            show_progress=False,
        )
        assert result == model_file
        assert len(model_file.read_bytes()) == len(full_payload)


def test_ensure_model_file_network_error_cleans_up_tmp(tmp_path: Path) -> None:
    """If network error occurs mid-download, .tmp file is purged and RuntimeError raised."""
    model_file = tmp_path / "model.onnx"
    temp_file = model_file.with_suffix(".onnx.tmp")

    def failing_urlopen(*args: object, **kwargs: object) -> None:
        # Create temp file to simulate partial download
        temp_file.write_bytes(b"PARTIAL")
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=failing_urlopen):
        with pytest.raises(RuntimeError, match="Failed to auto-download model weights"):
            ensure_model_file(
                dest_path=model_file,
                min_size=100,
                show_progress=False,
            )

        # Temporary file must be removed
        assert not temp_file.exists()
        assert not model_file.exists()


def test_ensure_ocr_model_files_unsupported_language() -> None:
    """Unsupported language returns None immediately."""
    assert ensure_ocr_model_files("fr") is None
    assert ensure_ocr_model_files("es") is None


def test_ensure_ocr_model_files_already_exists(tmp_path: Path) -> None:
    """If OCR model already exists with valid size, returns path without downloading."""
    model_file = tmp_path / "PP-OCRv6_rec_medium.onnx"
    # Write enough dummy bytes (>72MB threshold)
    model_file.write_bytes(b"0" * (72_000_000 + 10))

    with patch("src.backend.detection.downloader.ensure_model_file") as mock_ensure:
        result = ensure_ocr_model_files("rec", dest_path=model_file)
        assert result == model_file
        mock_ensure.assert_not_called()


def test_ensure_ocr_model_files_downloads_when_missing(tmp_path: Path) -> None:
    """Missing model triggers download and returns resolved path."""
    det_file = tmp_path / "PP-OCRv6_det_medium.onnx"
    with patch("src.backend.detection.downloader.ensure_model_file", return_value=det_file) as mock_ensure:
        result = ensure_ocr_model_files("det", dest_path=det_file, auto_download=True)
        assert result == det_file
        mock_ensure.assert_called_once()

    ko_file = tmp_path / "korean_PP-OCRv5_rec_mobile.onnx"
    with patch("src.backend.detection.downloader.ensure_model_file", return_value=ko_file) as mock_ensure_ko:
        result_ko = ensure_ocr_model_files("ko", dest_path=ko_file, auto_download=True)
        assert result_ko == ko_file
        mock_ensure_ko.assert_called_once()


def test_ensure_ocr_model_files_offline_fallback(tmp_path: Path) -> None:
    """When download fails or offline, returns None gracefully without crashing."""
    model_file = tmp_path / "korean_PP-OCRv5_rec_mobile.onnx"
    with patch("src.backend.detection.downloader.ensure_model_file", side_effect=RuntimeError("Network offline")):
        result = ensure_ocr_model_files("ko", dest_path=model_file, auto_download=True)
        assert result is None

