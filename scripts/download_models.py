"""Automated Model Weights Downloader and Health Verifier for InkShift Local Engine.

Downloads ONNX model weights for on-device detection and OCR into .cache/inkshift/models/.
Ensures atomic downloads via temporary files and verifies inference session readiness.

Usage:
    python scripts/download_models.py [--force] [--dest DIR] [--verify-only]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
from pathlib import Path
import sys
import time
import urllib.request

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import onnxruntime as ort
from PIL import Image

from src.backend.config import Settings
from src.backend.detection.downloader import (
    YOLO11_MIN_SIZE_BYTES,
    YOLO11_MODEL_URL,
    ensure_model_file,
    format_bytes,
)

MODEL_SPECS = [
    {
        "name": "YOLO11s-seg Manga Detection & Segmentation ONNX",
        "filename": "yolo11s-seg.onnx",
        "url": YOLO11_MODEL_URL,
        "min_size_bytes": YOLO11_MIN_SIZE_BYTES,
    }
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
    except Exception as exc:
        print(f"\n[InkShift] [ERROR] Download failed for {dest_path.name}: {exc}")
        return False


async def verify_detector_readiness(model_path: Path) -> bool:
    """Verify that YOLO11s-seg loads the downloaded weights and infers cleanly."""
    print(f"\n[InkShift] [VERIFY] Verifying YOLO11s-seg with weights at: {model_path}")
    if not model_path.exists():
        print(f"[InkShift] [ERROR] Model file not found at {model_path}.")
        return False

    providers = [
        ("DmlExecutionProvider", {"device_id": 0}),
        "CPUExecutionProvider",
    ]

    try:
        session = ort.InferenceSession(str(model_path), providers=providers)
        active_provider = session.get_providers()[0]
        print(f"[InkShift] [SESSION] Active Execution Provider: {active_provider}")

        inputs = session.get_inputs()
        outputs = session.get_outputs()
        print(f"[InkShift] [SESSION] Inputs: {[i.name for i in inputs]}")
        print(f"[InkShift] [SESSION] Outputs: {[o.name for o in outputs]} (Shapes: {[o.shape for o in outputs]})")

        # Smoke inference with dummy 1024x1024 tensor
        import numpy as np
        dummy = np.zeros((1, 3, 1024, 1024), dtype=np.float32)
        t0 = time.perf_counter()
        res = session.run(None, {inputs[0].name: dummy})
        lat = (time.perf_counter() - t0) * 1000
        print(f"[InkShift] [PASS] YOLO11s-seg smoke inference successful in {lat:.1f}ms! Output shapes: {[r.shape for r in res]}")
        return True
    except Exception as err:
        print(f"[InkShift] [ERROR] Failed to initialize YOLO11s-seg session: {err}")
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

    args = parser.parse_args()

    settings = Settings()
    dest_dir = Path(args.dest) if args.dest else Path(settings.inkshift_local_model_dir)

    print("=" * 60)
    print("   InkShift On-Device Model Provisioner")
    print(f"   Target Directory: {dest_dir.resolve()}")
    print("=" * 60)

    if not args.verify_only:
        for spec in MODEL_SPECS:
            dest_file = dest_dir / str(spec["filename"])
            success = download_file(
                url=str(spec["url"]),
                dest_path=dest_file,
                min_size=int(spec["min_size_bytes"]),
                force=args.force,
            )
            if not success:
                print(f"[InkShift] [ERROR] Aborting: Could not obtain {spec['name']}.")
                return 1

    # Verify readiness
    yolo_model_path = dest_dir / "yolo11s-seg.onnx"
    if not yolo_model_path.exists():
        print(f"[InkShift] [ERROR] Model file not found at {yolo_model_path}.")
        return 1

    verified = asyncio.run(verify_detector_readiness(yolo_model_path))
    if not verified:
        print("[InkShift] [ERROR] Model verification failed.")
        return 1

    print("\n" + "=" * 60)
    print("[SUCCESS] ALL MODELS READY FOR LIVE ON-DEVICE TRANSLATION!")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
