"""Automated model weights downloader and cache manager for InkShift.

Handles streaming download of ONNX model weights (e.g. YOLO11s-seg from Hugging Face)
with progress tracking, atomic write via temporary file, and size verification.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("inkshift.backend.downloader")

YOLO11_MODEL_URL = "https://huggingface.co/chiqui7/yolo11-manga-seg/resolve/main/yolo11s-seg.onnx"
YOLO11_MIN_SIZE_BYTES = 38_000_000  # ~39.3 MB

OCR_JA_MODEL_URL = "https://huggingface.co/breezedeus/cnocr-ppocr-japan_PP-OCRv3/resolve/main/japan_PP-OCRv3_rec_infer.onnx"
OCR_JA_MIN_SIZE_BYTES = 9_000_000  # ~10.1 MB

OCR_KO_MODEL_URL = "https://huggingface.co/breezedeus/cnocr-ppocr-korean_PP-OCRv3/resolve/main/korean_PP-OCRv3_rec_infer.onnx"
OCR_KO_MIN_SIZE_BYTES = 9_000_000  # ~9.9 MB


def format_bytes(num_bytes: int) -> str:
    """Format byte count into human-readable MB string."""
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def ensure_model_file(
    dest_path: str | Path,
    url: str = YOLO11_MODEL_URL,
    min_size: int = YOLO11_MIN_SIZE_BYTES,
    force: bool = False,
    show_progress: bool = True,
    timeout: float = 120.0,
) -> Path:
    """Ensure that the model weights file exists at dest_path and is complete.

    If missing or undersized, downloads the file atomically via streaming chunks.

    Args:
        dest_path: Target local file path for model weights.
        url: Remote download URL (default: Hugging Face YOLO11s-seg ONNX).
        min_size: Minimum expected file size in bytes to guard against partial downloads.
        force: If True, re-downloads even if file already exists.
        show_progress: If True, prints download progress to console.
        timeout: Network socket timeout in seconds.

    Returns:
        Resolved Path to the validated model file.

    Raises:
        RuntimeError: If download fails due to network or verification error.
    """
    path = Path(dest_path).resolve()

    if path.exists() and not force:
        current_size = path.stat().st_size
        if current_size >= min_size:
            logger.debug(
                "Model file already present and valid: %s (%s)",
                path.name,
                format_bytes(current_size),
            )
            return path
        logger.warning(
            "Existing model file %s is undersized (%s < %s). Re-downloading...",
            path.name,
            format_bytes(current_size),
            format_bytes(min_size),
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    print(f"\n[InkShift:AutoDownload] Model weights not found: {path.name}")
    print(f"[InkShift:AutoDownload] Downloading from Hugging Face: {url}")
    print(f"[InkShift:AutoDownload] Destination: {path}")

    start_time = time.time()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "InkShift-Model-Downloader/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response, open(temp_path, "wb") as out_file:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB chunks
            last_print_time = 0.0

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)

                current_now = time.time()
                if show_progress and (current_now - last_print_time >= 0.3 or (total_size and downloaded >= total_size)):
                    percent_str = f"({(downloaded / total_size) * 100:.1f}%)" if total_size > 0 else ""
                    print(
                        f"\r[InkShift:AutoDownload] Progress: {format_bytes(downloaded)} / {format_bytes(total_size)} {percent_str}",
                        end="",
                        flush=True,
                    )
                    last_print_time = current_now

        if show_progress:
            print()  # newline after progress bar

        actual_size = temp_path.stat().st_size
        if actual_size < min_size:
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(
                f"Downloaded file {path.name} is undersized ({actual_size} bytes < {min_size} bytes)."
            )

        if path.exists():
            path.unlink()
        temp_path.rename(path)

        elapsed = time.time() - start_time
        speed = (downloaded / (1024 * 1024)) / (elapsed if elapsed > 0 else 0.001)
        print(
            f"[InkShift:AutoDownload] Successfully installed {path.name} ({format_bytes(actual_size)}) in {elapsed:.1f}s ({speed:.1f} MB/s).\n"
        )
        return path

    except Exception as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        error_msg = (
            f"Failed to auto-download model weights for '{path.name}': {exc}. "
            "Please check your internet connection or run 'python scripts/download_models.py' manually."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg) from exc


def ensure_ocr_model_files(
    language: str,
    dest_path: str | Path | None = None,
    auto_download: bool = True,
) -> Path | None:
    """Ensure that specialized OCR ONNX model weights exist for the requested language.

    If missing and auto_download is True, attempts atomic streaming download.
    If download fails or offline, logs a warning and returns None for graceful fallback.

    Args:
        language: Language code ('ja', 'japanese', 'ko', 'korean').
        dest_path: Optional explicit local path for the model weights file.
        auto_download: Whether to attempt remote download if file is missing.

    Returns:
        Resolved Path to the validated model file, or None if unavailable.
    """
    normalized = language.lower().strip()
    if normalized in ("ja", "japanese"):
        url = OCR_JA_MODEL_URL
        min_size = OCR_JA_MIN_SIZE_BYTES
        filename = "japan_PP-OCRv3_rec_infer.onnx"
    elif normalized in ("ko", "korean"):
        url = OCR_KO_MODEL_URL
        min_size = OCR_KO_MIN_SIZE_BYTES
        filename = "korean_PP-OCRv3_rec_infer.onnx"
    else:
        return None

    from src.backend.config import Settings

    settings = Settings()
    if dest_path is None:
        target_path = Path(settings.inkshift_local_model_dir) / filename
    else:
        target_path = Path(dest_path).resolve()

    if target_path.exists() and target_path.stat().st_size >= min_size:
        return target_path

    if not auto_download or not settings.inkshift_auto_download_models:
        logger.warning(
            "OCR model weights missing for language '%s' at %s (auto-download disabled).",
            language,
            target_path,
        )
        return None

    try:
        logger.info(
            "Auto-downloading specialized OCR model weights for language '%s' to %s...",
            language,
            target_path,
        )
        return ensure_model_file(dest_path=target_path, url=url, min_size=min_size)
    except Exception as exc:
        logger.warning(
            "Could not download OCR model for language '%s' (%s). Gracefully falling back to default model.",
            language,
            exc,
        )
        return None

