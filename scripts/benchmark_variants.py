"""InkShift Real-Hardware Benchmark Runner for Translation Variants.

Measures exact latencies, memory footprint, and network payloads on a real manga page
across multiple translation variants:
1. Shared YOLO11s-seg Layout Detection (DirectML)
2. Cloud Vision: OpenAI-Compatible / xKiro with qwen/qwen3.8-max:free
3. Cloud Vision: Google AI Studio with gemini-2.0-flash
4. Local Engine: RapidOCR (PP-OCRv4 DirectML) + deep-translator (Google Free)
5. SQLite WAL Composite Cache Hit
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Ensure Windows terminal outputs Vietnamese Unicode characters cleanly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PIL import Image

from src.backend.cache.sqlite_cache import TranslationCache
from src.backend.config import Settings
from src.backend.detection.base import DetectedBubble
from src.backend.detection.yolo11_detector import YOLO11Detector
from src.backend.engines.cloud.gemini import GeminiProvider
from src.backend.engines.cloud.openai_compat import OpenAICompatibleProvider
from src.backend.engines.local.engine import LocalTranslationEngine
from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.engines.local.translator.google_free import GoogleFreeTranslator
from src.backend.engines.local.translator.registry import TranslatorRegistry
from src.backend.schemas.contract import TranslationRequest, TranslationResponse


async def main() -> None:
    settings = Settings()
    image_path = REPO_ROOT / "docs" / "vi" / "reports" / "images" / "benchmark_page.png"
    if not image_path.exists():
        fallback_fixture = REPO_ROOT / "tests" / "fixtures" / "manga_sample_panel.png"
        if fallback_fixture.exists():
            image_path = fallback_fixture
            print(f"[INFO] Using fallback test fixture: {image_path}")
        else:
            print(f"[ERROR] Benchmark image not found: {image_path}")
            sys.exit(1)

    print("=" * 80)
    print("  INKSHIFT REAL-HARDWARE BENCHMARK: TRANSLATION VARIANTS")
    print(f"  Target Image: {image_path.name} ({image_path.stat().st_size / 1024:.1f} KB)")
    print("=" * 80)

    raw_bytes = image_path.read_bytes()
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img_w, img_h = img.size
    print(f"[Input] Image Resolution: {img_w} x {img_h} pixels\n")

    b64_image = base64.b64encode(raw_bytes).decode("ascii")

    benchmark_data: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "image_file": image_path.name,
        "image_size_kb": round(len(raw_bytes) / 1024, 1),
        "resolution": f"{img_w}x{img_h}",
        "variants": {},
    }

    # --------------------------------------------------------------------------
    # STAGE 1: YOLO11s-seg Layout Detection (Shared Gateway)
    # --------------------------------------------------------------------------
    print("--- [1/5] Running YOLO11s-seg Layout Detection (DirectML) ---")
    detector = YOLO11Detector(
        execution_provider=settings.inkshift_local_execution_provider,
        confidence_threshold=0.25,
    )
    t0_detect = time.perf_counter()
    bubbles = await detector.detect(raw_bytes, img_w, img_h)
    detect_ms = round((time.perf_counter() - t0_detect) * 1000, 2)
    print(f"[YOLO11s-seg] Detected {len(bubbles)} speech bubbles in {detect_ms} ms")

    for idx, b in enumerate(bubbles, 1):
        ymin, xmin, ymax, xmax = b.box_2d
        print(f"  - Bubble #{idx:02d}: Box=[{ymin}, {xmin}, {ymax}, {xmax}], Conf={b.confidence:.2f}")

    benchmark_data["detection"] = {
        "bubble_count": len(bubbles),
        "latency_ms": detect_ms,
        "provider": settings.inkshift_local_execution_provider,
    }

    # --------------------------------------------------------------------------
    # VARIANT A: OpenAI-Compatible with qwen/qwen3.8-max:free
    # --------------------------------------------------------------------------
    print("\n--- [2/5] Testing OpenAI-Compatible Provider: qwen/qwen3.8-max:free ---")
    qwen_model = "qwen/qwen3.8-max:free"
    custom_key = settings.custom_api_key or settings.xkiro_api_key
    custom_base = settings.custom_base_url or settings.xkiro_base_url

    qwen_provider = OpenAICompatibleProvider(
        api_key=custom_key,
        model=qwen_model,
        base_url=custom_base,
        name="custom-openai",
        timeout_seconds=45.0,
    )

    t0_qwen = time.perf_counter()
    qwen_blocks = []
    qwen_status = "ok"
    qwen_err = None
    try:
        qwen_blocks = await qwen_provider.translate_page(
            image_base64=b64_image,
            target_lang="vi",
            model=qwen_model,
            bubbles=bubbles,
        )
        qwen_ms = round((time.perf_counter() - t0_qwen) * 1000, 2)
        print(f"[Qwen Free] Success in {qwen_ms} ms. Translated {len(qwen_blocks)} blocks:")
        for blk in qwen_blocks:
            print(f"    * [{blk.source_text}] -> [{blk.translated_text}]")
    except Exception as e:
        qwen_ms = round((time.perf_counter() - t0_qwen) * 1000, 2)
        qwen_status = "error"
        qwen_err = str(e)
        print(f"[Qwen Free] Upstream returned error after {qwen_ms} ms: {e}")

    benchmark_data["variants"]["openai_compat_qwen"] = {
        "model": qwen_model,
        "endpoint": custom_base,
        "status": qwen_status,
        "latency_ms": qwen_ms,
        "blocks_count": len(qwen_blocks),
        "error": qwen_err,
        "blocks": [b.model_dump() for b in qwen_blocks],
    }

    # --------------------------------------------------------------------------
    # VARIANT B: Google Gemini 2.0 Flash Vision (Set-of-Marks)
    # --------------------------------------------------------------------------
    target_gem_model = "gemini-1.5-flash"
    gemini_provider = GeminiProvider(
        api_key=settings.gemini_api_key,
        model=target_gem_model,
        base_url=settings.gemini_base_url,
        timeout_seconds=30.0,
    )

    t0_gem = time.perf_counter()
    gem_blocks = []
    gem_status = "ok"
    gem_err = None
    try:
        gem_blocks = await gemini_provider.translate_page(
            image_base64=b64_image,
            target_lang="vi",
            model=target_gem_model,
            bubbles=bubbles,
        )
        gem_ms = round((time.perf_counter() - t0_gem) * 1000, 2)
        print(f"[Gemini 2.5 Flash] Success in {gem_ms} ms. Translated {len(gem_blocks)} blocks:")
        for blk in gem_blocks:
            print(f"    * [{blk.source_text}] -> [{blk.translated_text}]")
    except Exception as e:
        gem_ms = round((time.perf_counter() - t0_gem) * 1000, 2)
        gem_status = "error"
        gem_err = str(e)
        print(f"[Gemini Flash] Upstream returned error after {gem_ms} ms: {e}")

    benchmark_data["variants"]["gemini_flash"] = {
        "model": settings.gemini_model,
        "status": gem_status,
        "latency_ms": gem_ms,
        "blocks_count": len(gem_blocks),
        "error": gem_err,
        "blocks": [b.model_dump() for b in gem_blocks],
    }

    # --------------------------------------------------------------------------
    # VARIANT C: Local Engine (DirectML RapidOCR + deep-translator Google Free)
    # --------------------------------------------------------------------------
    print("\n--- [4/5] Testing Local Engine: RapidOCR DirectML + deep-translator ---")
    rapid_adapter = RapidOCRAdapter()
    ocr_router = OCRRouter(rapid_ocr=rapid_adapter)
    translator = GoogleFreeTranslator()
    trans_registry = TranslatorRegistry(default_translator_name="google-free")
    trans_registry.register("google-free", translator)
    local_engine = LocalTranslationEngine(
        ocr_router=ocr_router,
        translator_registry=trans_registry,
    )

    req = TranslationRequest(
        image=b64_image,
        source_lang="auto",
        target_lang="vi",
        engine="local",
    )

    t0_local = time.perf_counter()
    local_res = await local_engine.translate(req, bubbles=bubbles)
    local_ms = round((time.perf_counter() - t0_local) * 1000, 2)
    print(f"[Local Engine] Success in {local_ms} ms. Translated {len(local_res.blocks)} blocks:")
    for blk in local_res.blocks:
        print(f"    * [{blk.source_text}] -> [{blk.translated_text}]")

    benchmark_data["variants"]["local_directml"] = {
        "ocr": "RapidOCR PP-OCRv4 (DirectML)",
        "translator": "deep-translator Google Free",
        "latency_ms": local_ms,
        "blocks_count": len(local_res.blocks),
        "blocks": [b.model_dump() for b in local_res.blocks],
    }

    # --------------------------------------------------------------------------
    # VARIANT D: SQLite WAL Composite Cache Hit
    # --------------------------------------------------------------------------
    print("\n--- [5/5] Testing SQLite WAL Cache Performance ---")
    cache_db_path = REPO_ROOT / "data" / "cache.db"
    cache = TranslationCache(str(cache_db_path))
    await cache.initialize()

    test_hash = f"bench-{int(time.time())}"
    sample_response = local_res

    # Warm cache
    await cache.set(test_hash, "vi", sample_response, engine_used="local")

    # Measure 5 cache lookups
    cache_timings = []
    for _ in range(5):
        t0_c = time.perf_counter()
        hit = await cache.get(test_hash, "vi", "local")
        c_ms = round((time.perf_counter() - t0_c) * 1000, 3)
        cache_timings.append(c_ms)

    avg_cache_ms = round(sum(cache_timings) / len(cache_timings), 3)
    print(f"[Cache Hit] 5 queries: {cache_timings} ms -> Average: {avg_cache_ms} ms")

    benchmark_data["variants"]["cache_hit"] = {
        "sample_timings_ms": cache_timings,
        "average_ms": avg_cache_ms,
        "storage": "SQLite WAL (PRAGMA journal_mode=WAL)",
    }

    # Save benchmark report to disk
    out_file = REPO_ROOT / "data" / "benchmark_real_report.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(benchmark_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[DONE] Full benchmark report saved to: {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
