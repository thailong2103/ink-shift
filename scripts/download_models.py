"""Automated Model Weights Downloader and Health Verifier for InkShift Local Engine.

Downloads ONNX model weights for on-device detection and OCR into .cache/inkshift/models/.
Ensures atomic downloads via temporary files and verifies inference session readiness on DirectML.

Usage:
    python scripts/download_models.py [--force] [--dest DIR] [--verify-only] [--include-korean]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import TypedDict

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except (OSError, AttributeError, ValueError):
        sys.stderr.write("[InkShift] Warning: UTF-8 console reconfigure unavailable.\n")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import onnxruntime as ort

from src.backend.config import Settings
from src.backend.detection.downloader import (
    OCR_DET_MIN_SIZE_BYTES,
    OCR_DET_MODEL_URL,
    OCR_KO_MIN_SIZE_BYTES,
    OCR_KO_MODEL_URL,
    OCR_REC_MIN_SIZE_BYTES,
    OCR_REC_MODEL_URL,
    YOLO11_MIN_SIZE_BYTES,
    YOLO11_MODEL_URL,
    ensure_model_file,
)


class ModelSpec(TypedDict):
    """Typed descriptor for a downloadable ONNX model weight artifact."""

    name: str
    filename: str
    url: str
    min_size_bytes: int
    optional: bool


MODEL_SPECS: list[ModelSpec] = [
    {
        "name": "YOLO11s-seg Manga Detection & Segmentation ONNX",
        "filename": "yolo11s-seg.onnx",
        "url": YOLO11_MODEL_URL,
        "min_size_bytes": YOLO11_MIN_SIZE_BYTES,
        "optional": False,
    },
    {
        "name": "PP-OCRv6_det_medium Multilingual Text Detector ONNX",
        "filename": "PP-OCRv6_det_medium.onnx",
        "url": OCR_DET_MODEL_URL,
        "min_size_bytes": OCR_DET_MIN_SIZE_BYTES,
        "optional": False,
    },
    {
        "name": "PP-OCRv6_rec_medium Multilingual (ZH/JA/EN) Recognizer ONNX",
        "filename": "PP-OCRv6_rec_medium.onnx",
        "url": OCR_REC_MODEL_URL,
        "min_size_bytes": OCR_REC_MIN_SIZE_BYTES,
        "optional": False,
    },
    {
        "name": "Korean PP-OCRv5_rec_mobile Recognizer ONNX",
        "filename": "korean_PP-OCRv5_rec_mobile.onnx",
        "url": OCR_KO_MODEL_URL,
        "min_size_bytes": OCR_KO_MIN_SIZE_BYTES,
        "optional": True,
    },
]


def download_file(url: str, dest_path: Path, min_size: int, force: bool = False) -> bool:
    """Download a file with streaming chunks and progress display."""
    try:
        ensure_model_file(
            dest_path=dest_path,
            url=url,
            min_size=min_size,
            force=force,
            show_progress=True,
        )
        return True
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"\n[InkShift] [ERROR] Download failed for {dest_path.name}: {exc}")
        return False


def _open_dml_or_cpu_session(model_path: Path) -> ort.InferenceSession:
    """Initialize ONNX Runtime session preferring DirectML with CPU fallback."""
    providers: list[object] = [
        ("DmlExecutionProvider", {"device_id": 0}),
        "CPUExecutionProvider",
    ]
    return ort.InferenceSession(str(model_path), providers=providers)


async def verify_detector_readiness(model_path: Path) -> bool:
    """Verify that YOLO11s-seg loads the downloaded weights and infers cleanly."""
    print(f"\n[InkShift] [VERIFY] Verifying YOLO11s-seg with weights at: {model_path}")
    if not model_path.exists():
        print(f"[InkShift] [ERROR] Model file not found at {model_path}.")
        return False

    try:
        session = _open_dml_or_cpu_session(model_path)
        active_provider = session.get_providers()[0]
        print(f"[InkShift] [SESSION] Active Execution Provider: {active_provider}")

        inputs = session.get_inputs()
        outputs = session.get_outputs()
        print(f"[InkShift] [SESSION] Inputs: {[i.name for i in inputs]}")
        print(f"[InkShift] [SESSION] Outputs: {[o.name for o in outputs]} (Shapes: {[o.shape for o in outputs]})")

        dummy = np.zeros((1, 3, 1024, 1024), dtype=np.float32)
        t0 = time.perf_counter()
        res = session.run(None, {inputs[0].name: dummy})
        lat = (time.perf_counter() - t0) * 1000
        print(f"[InkShift] [PASS] YOLO11s-seg smoke inference successful in {lat:.1f}ms! Output shapes: {[r.shape for r in res]}")
        return True
    except (RuntimeError, OSError, ValueError) as err:
        print(f"[InkShift] [ERROR] Failed to initialize YOLO11s-seg session: {err}")
        return False


def verify_ppocrv6_readiness(det_path: Path, rec_path: Path, ko_path: Path | None = None) -> bool:
    """Verify PP-OCRv6_medium det/rec (and optional Korean rec) ONNX sessions + embedded dict metadata."""
    print(f"\n[InkShift] [VERIFY] Verifying PP-OCRv6_det_medium at: {det_path}")
    if not det_path.exists() or not rec_path.exists():
        print("[InkShift] [ERROR] PP-OCRv6 det or rec model missing on disk.")
        return False

    try:
        det_sess = _open_dml_or_cpu_session(det_path)
        det_provider = det_sess.get_providers()[0]
        det_in = det_sess.get_inputs()[0]
        dummy_det = np.zeros((1, 3, 640, 640), dtype=np.float32)
        t0 = time.perf_counter()
        det_out = det_sess.run(None, {det_in.name: dummy_det})
        det_ms = (time.perf_counter() - t0) * 1000
        print(
            f"[InkShift] [PASS] PP-OCRv6_det_medium ({det_provider}) smoke inference in {det_ms:.1f}ms! "
            f"Output shape: {[r.shape for r in det_out]}"
        )

        print(f"[InkShift] [VERIFY] Verifying PP-OCRv6_rec_medium at: {rec_path}")
        rec_sess = _open_dml_or_cpu_session(rec_path)
        rec_provider = rec_sess.get_providers()[0]
        rec_meta = rec_sess.get_modelmeta().custom_metadata_map
        char_str = rec_meta.get("character", "")
        if not char_str:
            print("[InkShift] [ERROR] PP-OCRv6_rec_medium missing embedded 'character' metadata!")
            return False
        char_lines = [line for line in char_str.splitlines() if line]
        rec_in = rec_sess.get_inputs()[0]
        dummy_rec = np.zeros((1, 3, 48, 320), dtype=np.float32)
        t0 = time.perf_counter()
        rec_out = rec_sess.run(None, {rec_in.name: dummy_rec})
        rec_ms = (time.perf_counter() - t0) * 1000
        print(
            f"[InkShift] [PASS] PP-OCRv6_rec_medium ({rec_provider}) smoke inference in {rec_ms:.1f}ms! "
            f"Embedded chars: {len(char_lines)}, Output shape: {[r.shape for r in rec_out]}"
        )

        if ko_path is not None and ko_path.exists():
            ko_sess = _open_dml_or_cpu_session(ko_path)
            ko_provider = ko_sess.get_providers()[0]
            ko_meta = ko_sess.get_modelmeta().custom_metadata_map
            ko_chars = [line for line in ko_meta.get("character", "").splitlines() if line]
            print(
                f"[InkShift] [PASS] korean_PP-OCRv5_rec_mobile ({ko_provider}) ready! "
                f"Embedded chars: {len(ko_chars)}"
            )

        return True
    except (RuntimeError, OSError, ValueError) as err:
        print(f"[InkShift] [ERROR] Failed to verify PP-OCRv6 sessions: {err}")
        return False


def main() -> int:
    """CLI entry point for model downloading and verification."""
    parser = argparse.ArgumentParser(description="Download and verify InkShift ONNX model weights.")
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force re-download even if model files already exist on disk.",
    )
    parser.add_argument(
        "--dest", "-d",
        type=str,
        default=None,
        help="Custom destination directory for model weights.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip downloading and only verify existing model files.",
    )
    parser.add_argument(
        "--include-korean",
        action="store_true",
        help="Also pre-download korean_PP-OCRv5_rec_mobile.onnx (otherwise lazy-downloaded on first Korean chapter).",
    )

    args = parser.parse_args()

    settings = Settings()
    dest_dir = Path(args.dest) if args.dest else Path(settings.inkshift_local_model_dir)

    print("=" * 60)
    print("   InkShift On-Device Model Provisioner")
    print(f"   Target Directory: {dest_dir.resolve()}")
    print("=" * 60)

    if not args.verify_only:
        for spec in MODEL_SPECS:
            if spec["optional"] and not args.include_korean:
                continue
            dest_file = dest_dir / spec["filename"]
            success = download_file(
                url=spec["url"],
                dest_path=dest_file,
                min_size=spec["min_size_bytes"],
                force=args.force,
            )
            if not success:
                print(f"[InkShift] [ERROR] Aborting: Could not obtain {spec['name']}.")
                return 1

    yolo_model_path = dest_dir / "yolo11s-seg.onnx"
    det_model_path = dest_dir / "PP-OCRv6_det_medium.onnx"
    rec_model_path = dest_dir / "PP-OCRv6_rec_medium.onnx"
    ko_model_path = dest_dir / "korean_PP-OCRv5_rec_mobile.onnx"

    if not yolo_model_path.exists():
        print(f"[InkShift] [ERROR] Model file not found at {yolo_model_path}.")
        return 1

    verified_yolo = asyncio.run(verify_detector_readiness(yolo_model_path))
    verified_ocr = verify_ppocrv6_readiness(
        det_model_path,
        rec_model_path,
        ko_model_path if ko_model_path.exists() else None,
    )
    if not verified_yolo or not verified_ocr:
        print("[InkShift] [ERROR] Model verification failed.")
        return 1

    print("\n" + "=" * 60)
    print("[SUCCESS] ALL MODELS READY FOR LIVE ON-DEVICE TRANSLATION!")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
