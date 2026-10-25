"""Interactive CLI script to test live cloud vision translation with real API keys.

Usage examples:
    # 1. Using .env credentials with an image:
    python scripts/test_live_cloud.py --image path/to/manga_page.jpg

    # 2. Specifying Gemini API key directly:
    python scripts/test_live_cloud.py --image page.jpg --key AIzaSy...

    # 3. Testing xKiro / Qwen model:
    python scripts/test_live_cloud.py --provider xkiro --image page.jpg --key your_xkiro_key
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
from pathlib import Path
import sys
import time

# Ensure repository root is on sys.path for direct script execution
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

from src.backend.config import Settings
from src.backend.engines.cloud import (
    CloudEngineError,
    ContentSafetyBlockedError,
    GeminiProvider,
    OpenAICompatibleProvider,
    RateLimitExceededError,
    UpstreamAuthenticationError,
    UpstreamTimeoutError,
)
from src.backend.schemas.contract import TranslatedBlock


def read_image_base64(image_path: Path) -> str:
    """Read local image file and encode to raw Base64 string."""
    if not image_path.exists():
        print(f"[ERROR] Image file not found: {image_path}")
        sys.exit(1)

    raw_bytes = image_path.read_bytes()
    return base64.b64encode(raw_bytes).decode("ascii")


def print_results(
    provider_name: str,
    model_name: str,
    latency_ms: int,
    blocks: list[TranslatedBlock],
) -> None:
    """Display detected bubbles and Vietnamese translations in formatted output."""
    print("\n" + "=" * 70)
    print(f"  INKSHIFT LIVE TRANSLATION RESULT")
    print(f"  Provider: {provider_name.upper()} | Model: {model_name}")
    print(f"  Latency: {latency_ms} ms | Bubbles Detected: {len(blocks)}")
    print("=" * 70)

    if not blocks:
        print("\n[INFO] No speech bubbles detected on this page (scenery / splash page).")
        return

    for idx, block in enumerate(blocks, start=1):
        ymin, xmin, ymax, xmax = block.box
        print(f"\n--- Block #{idx} [{block.id}] ---")
        print(f"  Box [ymin, xmin, ymax, xmax] : [{ymin}, {xmin}, {ymax}, {xmax}] (0-1000 scale)")
        print(f"  Direction                     : {block.direction}")
        if block.confidence is not None:
            print(f"  Confidence                    : {block.confidence:.2f}")
        if block.source_text:
            print(f"  Original Text (Raw)           : {block.source_text}")
        print(f"  Vietnamese Translation        : {block.translated_text}")

    print("\n" + "=" * 70 + "\n")


async def run_live_test(
    provider_type: str,
    image_path: Path,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 45.0,
) -> None:
    """Execute live vision translation request against upstream AI provider."""
    settings = Settings()

    # Resolve active API key
    if provider_type == "gemini":
        active_key = api_key or settings.gemini_api_key
        active_model = model or settings.gemini_model
        if not active_key:
            print("\n[ERROR] Missing Gemini API key!")
            print("Please provide it via:")
            print("  - Command line: --key YOUR_API_KEY")
            print("  - Or add to .env: GEMINI_API_KEY=AIzaSy...")
            print("Get a free key at: https://aistudio.google.com/app/apikey\n")
            sys.exit(1)

        print(f"\n[InkShift] Initializing GeminiProvider ({active_model}, timeout={timeout:.0f}s)...")
        provider: GeminiProvider | OpenAICompatibleProvider = GeminiProvider(
            api_key=active_key,
            model=active_model,
            timeout_seconds=timeout,
        )

    else:
        active_key = api_key or settings.custom_api_key or settings.xkiro_api_key
        active_model = model or settings.custom_model or settings.xkiro_model
        if not active_key:
            print("\n[ERROR] Missing Custom / OpenAI-Compatible API key!")
            print("Please provide it via:")
            print("  - Command line: --key YOUR_API_KEY")
            print("  - Or add to .env: CUSTOM_API_KEY=...")
            print("Get a key from your provider or local host.\n")
            sys.exit(1)

        print(f"\n[InkShift] Initializing OpenAICompatibleProvider for Custom/OpenAI ({active_model or 'default'}, timeout={timeout:.0f}s)...")
        provider = OpenAICompatibleProvider(
            api_key=active_key,
            model=active_model,
            base_url=settings.custom_base_url or settings.xkiro_base_url,
            timeout_seconds=timeout,
        )

    # Encode image
    print(f"[InkShift] Reading image: {image_path} ({os.path.getsize(image_path) / 1024:.1f} KB)...")
    image_b64 = read_image_base64(image_path)

    # Send request
    print(f"[InkShift] Sending vision translation request to upstream provider...")
    start_time = time.perf_counter()

    try:
        blocks = await provider.translate_page(
            image_base64=image_b64,
            target_lang="vi",
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        print_results(provider.name, provider.default_model, latency_ms, blocks)

    except ContentSafetyBlockedError as err:
        print(f"\n[SAFETY BLOCKED] {err.message}")
        print("Model rejected this image due to safety/content policy. Fallback: local-engine.")
        sys.exit(2)

    except RateLimitExceededError as err:
        print(f"\n[RATE LIMITED] {err.message}")
        print("Free tier RPM/TPM limit reached. Please wait a moment before retrying.")
        sys.exit(3)

    except UpstreamAuthenticationError as err:
        print(f"\n[AUTH ERROR] {err.message}")
        print("Please check your API key.")
        sys.exit(4)

    except UpstreamTimeoutError as err:
        print(f"\n[TIMEOUT] {err.message}")
        print(f"Upstream API took more than {timeout:.0f}s to reply. Free tier gateways may be under load; try '--timeout 60'.")
        sys.exit(5)

    except CloudEngineError as err:
        print(f"\n[ENGINE ERROR] ({err.code}): {err.message}")
        sys.exit(6)


def main() -> None:
    parser = argparse.ArgumentParser(description="InkShift Live Cloud Vision Translation Tester")
    parser.add_argument(
        "--image",
        type=Path,
        required=True,
        help="Path to manga page image file (.jpg, .png, .webp)",
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "xkiro"],
        default="gemini",
        help="Target provider: 'gemini' (Google AI Studio) or 'xkiro' (default: gemini)",
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="Upstream API key (overrides .env setting)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model identifier override (e.g. 'gemini-3.8-flash', 'gemini-3.5-flash-lite', 'qwen/qwen3.8-max:free')",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="Timeout in seconds (default: 45.0s, recommended for free-tier model queues)",
    )

    args = parser.parse_args()
    asyncio.run(
        run_live_test(
            provider_type=args.provider,
            image_path=args.image,
            api_key=args.key,
            model=args.model,
            timeout=args.timeout,
        )
    )


if __name__ == "__main__":
    main()
