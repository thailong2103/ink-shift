# Spec: Cloud Vision Turbo Provider (`cloud-engine`)

> **Module ID:** `cloud-engine`  
> **Module ID:** `cloud-engine`  
> **Source ADR:** [ADR-004-cloud-engine-architecture.md](../decisions/ADR-004-cloud-engine-architecture.md), [ADR-007-yolo11-manga-detection-and-visual-grounding.md](../decisions/ADR-007-yolo11-manga-detection-and-visual-grounding.md), [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Contract Spec:** [SPEC-api-contract.md](SPEC-api-contract.md)  
> **Backend Spec:** [SPEC-backend-engine.md](SPEC-backend-engine.md)  
> **Status:** Approved by Solo Developer (@human)  
> **Phase:** Module 3 Execution Runtime (Universal Set-of-Marks & ProviderRegistry)  
> **Quality Gate:** [CONSTRAINTS.md](../../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)  
> **Language Policy:** Official English document tracked in Git. Parallel Vietnamese copy at [docs/vi/specs/SPEC-cloud-engine.md](../vi/specs/SPEC-cloud-engine.md).  

---

## 1. Assumptions Surface

Before proceeding to implementation, the following architectural assumptions are recorded:
1. **Credentials Management:** API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`) and active provider choices are loaded via environment variables / `.env`.
2. **Primary Provider:** Google AI Studio utilizing `gemini-2.5-flash` is the default provider due to ultra-low latency and multimodal reasoning.
3. **Set-of-Marks (SoM) Visual Grounding:** Rather than forcing Cloud LLMs to predict spatial coordinates, the API gateway executes shared YOLO11s-seg locally (~80ms), draws sequential numerical markers (`[1], [2], [3]...`) onto speech balloons, and sends the annotated image. The Cloud LLM translates dialogue indexed by marker ID.
4. **Zero-Bubble Optimization:** If the page contains 0 speech bubbles, cloud translation exits immediately with an empty block list, consuming **0 tokens, 0 network requests, and 0 latency**.
5. **Universal Provider Parity:** Both Gemini and OpenAI-compatible providers share the same visual grounding and flat JSON prompt format.
6. **Zero New SDK Dependencies:** All upstream requests are executed via `httpx.AsyncClient` already installed in `src/backend`.

---

## 2. Objective

Implement the Cloud Vision Turbo Provider (`cloud-engine`) using **Set-of-Marks (SoM) Visual Grounding** and dynamic `ProviderRegistry`. Given a raw manga page image and pre-detected bubbles from the gateway, the engine applies numerical badge markers, requests flat JSON translation mapping (`{"1": "...", "2": "..."}`) from the selected cloud LLM, and pairs translated text with YOLO11's ground-truth BBoxes and smooth polygon masks.

### Core Capabilities:
1. **Set-of-Marks Visual Grounding:** Pre-detected bubbles in Japanese RTL sequence receive 1px boundary outlines and high-contrast numerical badge markers (`[1], [2]...`) drawn at balloon top centers.
2. **Ultra-Compact Flat JSON Schema:** Upstream LLMs only output a flat JSON dictionary:
   ```json
   { "1": "Lời dịch câu 1", "2": "Lời dịch câu 2" }
   ```
   Eliminates coordinate prediction completely, cutting output tokens by 90% and latency from 15s to ~1s.
3. **100% Coordinate Fidelity:** Zero bounding box drift or hallucinated coordinates since spatial geometry comes directly from hardware-accelerated YOLO11 segmentation.
4. **Dynamic ProviderRegistry:**
   - `GeminiProvider`: Google AI Studio REST endpoint (`v1beta/models/{model}:generateContent`) with `responseMimeType: "application/json"`.
   - `OpenAICompatProvider`: Universal OpenAI `/chat/completions` gateway (targeting xKiro, DeepSeek, OpenRouter, or local Ollama).
5. **Single Canonical Engine Registration:** Registered in backend as canonical `"cloud"`, resolving provider dynamically from request payload `provider: "gemini" | "openai"`.
6. **Resilience & Rate-Limit Defense:** Automated exponential backoff with jitter on HTTP 429 ($\le 2$ retries), 15-second hard timeout, and graceful handling of empty images.

---

## 3. Tech Stack & Commands

### 3.1 Dependencies
- **Runtime:** Python 3.11+
- **HTTP Client:** `httpx >= 0.27.0` (async connection pooling)
- **Data Validation:** `pydantic >= 2.6.0` (contract models)
- **Backend Coordinator:** `fastapi >= 0.110.0`
- **Testing & Quality:** `pytest >= 8.0.0`, `pytest-asyncio >= 0.23.0`, `mypy >= 1.9.0`, `ruff >= 0.3.0`

### 3.2 Verification Commands
```bash
# Floor Guard + Strict Type Checking + Linting
python scripts/check.py --fast

# Full Test Suite with Coverage Gate (Must satisfy >= 80% per CONSTRAINTS.md)
python scripts/check.py --full

# Targeted Pytest Suite for Cloud Engine
pytest tests/backend/engines/test_cloud.py tests/backend/engines/cloud/ -v --asyncio-mode=auto
```

---

## 4. Project Structure

```
src/backend/
├── engines/
│   ├── base.py                     # BaseTranslationEngine (from Module 2)
│   ├── registry.py                 # EngineRegistry (from Module 2)
│   └── cloud/
│       ├── __init__.py             # Exports CloudTranslationEngine, GeminiProvider, OpenAICompatProvider
│       ├── engine.py               # CloudTranslationEngine (delegates to ProviderRegistry)
│       ├── provider.py             # CloudProvider Protocol definition
│       ├── provider_registry.py    # Dynamic ProviderRegistry (gemini, openai)
│       ├── visual_grounding.py     # Set-of-Marks image markup & badge drawing
│       ├── prompts.py              # Manga localization system instructions & JSON Schema specs
│       ├── gemini.py               # GeminiProvider (Google AI Studio REST implementation)
│       ├── openai_compat.py        # OpenAICompatProvider (OpenAI wire format with SoM)
│       └── exceptions.py           # Structured cloud engine error hierarchy

tests/backend/engines/
├── test_cloud.py                   # Comprehensive unit tests for Cloud providers, 429 retry, SoM flow
└── cloud/
    ├── test_openai_compat.py       # OpenAICompatProvider unit tests and error handling
    └── test_provider_registry.py   # Dynamic provider resolution and registration tests
```

---

## 5. Architecture & Code Conventions

### 5.1 Provider Protocol (`src/backend/engines/cloud/provider.py`)
```python
from typing import Protocol, runtime_checkable
from src.backend.schemas.contract import TranslatedBlock


@runtime_checkable
class CloudProvider(Protocol):
    """Protocol for concrete cloud vision providers (Gemini, xKiro/OpenAI)."""

    @property
    def name(self) -> str:
        """Provider identifier (e.g. 'gemini', 'xkiro')."""
        ...

    @property
    def default_model(self) -> str:
        """Default model identifier (e.g. 'gemini-3.8-flash', 'qwen/qwen3.8-max')."""
        ...

    async def is_available(self) -> bool:
        """Check whether provider credentials and endpoints are configured."""
        ...

    async def translate_page(
        self,
        image_base64: str,
        target_lang: str = "vi",
        model: str | None = None,
    ) -> list[TranslatedBlock]:
        """Execute single-pass vision translation and return structured blocks."""
        ...
```

### 5.2 Composite Engine (`src/backend/engines/cloud/engine.py`)
`CloudTranslationEngine` implements `BaseTranslationEngine`. It extracts raw base64 data, delegates to the active `CloudProvider`, records execution latency, and constructs a canonical `TranslationResponse`:

```python
import time
from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.cloud.provider import CloudProvider
from src.backend.schemas.contract import TranslationRequest, TranslationResponse


class CloudTranslationEngine(BaseTranslationEngine):
    """Composite translation engine delegating to an active CloudProvider."""

    def __init__(self, provider: CloudProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return f"cloud:{self._provider.name}"

    async def is_available(self) -> bool:
        return await self._provider.is_available()

    async def translate(self, request: TranslationRequest) -> TranslationResponse:
        start_time = time.perf_counter()
        
        # Clean data URL prefix if present
        raw_b64 = request.image
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]

        blocks = await self._provider.translate_page(
            image_base64=raw_b64,
            target_lang=request.target_lang,
        )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return TranslationResponse(
            success=True,
            page_hash=request.image_hash or "0" * 64,
            engine_used=self.name,
            execution_time_ms=latency_ms,
            from_cache=False,
            blocks=blocks,
        )
```

### 5.3 Manga Localization Prompt (`src/backend/engines/cloud/prompts.py`)
Prompting is tuned specifically for manga layout understanding:

```python
MANGA_SYSTEM_PROMPT = """You are an expert manga localizer and translator.
Analyze the provided manga page image:
1. Detect all dialogue speech bubbles, narrative captions, and significant sound effects (SFX).
2. For each detected text block, extract:
   - box_2d: Normalized bounding box [ymin, xmin, ymax, xmax] as integers between 0 and 1000.
   - source_text: Raw transcription of the original text.
   - translated_text: Natural, context-aware Vietnamese translation respecting manga tone, honorifics, and character dynamics.
   - direction: 'vertical' (for traditional Japanese RTL columns) or 'horizontal'.
3. Follow the natural Japanese manga reading order (Right-to-Left, Top-to-Bottom).
4. Output strictly a JSON array conforming to the specified schema. If the page contains no text, output an empty array [].
"""
```

---

## 6. Error Handling & Resilience Matrix

The engine intercepts network exceptions and model failure modes, mapping them strictly into InkShift error codes:

| Failure Mode | Root Cause | Handling Strategy | API Error Code |
|---|---|---|---|
| **Rate Limit** | HTTP 429 Too Many Requests | Exponential backoff with jitter: retry after 1.0s, then 2.0s ($\le 2$ retries). If still 429, fail cleanly. | `RATE_LIMIT_EXCEEDED` |
| **Auth Error** | HTTP 401 / 403 Invalid API Key | No retry. Immediately return descriptive error. | `INVALID_API_KEY` |
| **Timeout / Hang** | Upstream latency $>15$s | Abort via `httpx.Timeout(15.0, connect=5.0)`. | `UPSTREAM_TIMEOUT` |
| **Safety Refusal** | Gemini `finishReason == "SAFETY"` / `BLOCKLIST`, or Qwen refusal text | Detect safety trigger; advise user to fall back to `local-engine`. | `CONTENT_SAFETY_BLOCKED` |
| **JSON Parse Error** | Markdown codefence or malformed JSON | Strip ````json ```` fences; attempt regex JSON block extraction; raise clean error if unparseable. | `ENGINE_EXECUTION_FAILED` |
| **Empty Response** | Genuine 0-bubble page (scenery / splash page) | Successfully return `TranslationResponse(success=True, blocks=[])`. | *(None — Valid 200)* |

---

## 7. Testing Strategy

1. **Unit Testing (`pytest tests/backend/engines/test_cloud.py`):**
   - **GeminiProvider Tests:** Mock `httpx` response returning valid JSON Schema; verify `[ymin, xmin, ymax, xmax]` normalized coordinates `[0, 1000]`.
   - **OpenAICompatibleProvider Tests:** Mock `httpx` response with markdown codefence wrapping (` ```json [...] ``` `); verify regex stripper and JSON validation.
   - **Retry & Backoff Tests:** Mock initial 429 followed by 200; verify exponential backoff succeeds. Mock persistent 429; verify `RATE_LIMIT_EXCEEDED` raised.
   - **Safety Refusal Tests:** Mock Gemini response with `finishReason: "SAFETY"`; verify `CONTENT_SAFETY_BLOCKED` raised. Mock Qwen refusal string; verify refusal heuristic catches it.
   - **Timeout Tests:** Mock `httpx.ReadTimeout`; verify `UPSTREAM_TIMEOUT` raised without crashing server loop.
   - **Empty Page Tests:** Mock empty JSON array `[]`; verify `TranslationResponse(blocks=[])` returned.
2. **Quality & Coverage Verification:**
   - Execute `python scripts/check.py --fast` (Floor guard, ruff, mypy strict).
   - Execute `python scripts/check.py --task` ensuring test coverage across `src/backend/engines/cloud/` satisfies $\ge 80\%$ per [CONSTRAINTS.md](../../CONSTRAINTS.md).

---

## 8. Boundaries

- **Always:** Use `httpx.AsyncClient` with an explicit 15s timeout; validate bounding boxes against `[0, 1000]`; strip Data URL prefixes before transmission; return structured error codes.
- **Ask First:** Adding external SDK packages (`google-genai`, `openai`); altering default prompt templates; modifying the retry policy budget beyond 2 retries.
- **Never:** Suppress type errors with `# type: ignore` or `# noqa`; block the async event loop with synchronous sleeps; log raw API keys in plain text; silently swallow safety policy rejections.

---

## 9. Success Criteria

- [ ] **SC-1:** `GeminiProvider` connects to Google AI Studio REST API using `gemini-3.8-flash` and extracts valid `TranslatedBlock` objects with coordinates in `[0, 1000]`.
- [ ] **SC-2:** `OpenAICompatibleProvider` connects to xKiro/OpenAI endpoints using `qwen/qwen3.8-max` and parses JSON output defensively.
- [ ] **SC-3:** `CloudTranslationEngine` integrates seamlessly with `EngineRegistry` and responds to `POST /api/v1/translate` with `engine="cloud"`.
- [ ] **SC-4:** Rate-limited requests (HTTP 429) automatically retry with exponential backoff and jitter.
- [ ] **SC-5:** Safety policy blocks (`finishReason: "SAFETY"`) return structured `CONTENT_SAFETY_BLOCKED` without crashing.
- [ ] **SC-6:** Zero type errors under `mypy src/backend --strict`.
- [ ] **SC-7:** Zero lint violations under `ruff check src/backend`.
- [ ] **SC-8:** Test coverage across new cloud engine code satisfies $\ge 80\%$ per `CONSTRAINTS.md`.

---

## 10. Open Questions

*(All primary architectural choices were resolved and documented in [ADR-004](../decisions/ADR-004-cloud-engine-architecture.md) and [ADR-008](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md). No open questions remain.)*

---

## 11. Addendum: Fine-Grained Set-of-Marks Grounding for Multi-Child Bubbles (Option A)

> **Approved by:** Solo Developer (@human)  
> **Date:** 2026-10-18  
> **Reference Decision:** [ADR-008 Addendum](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md#addendum-fine-grained-set-of-marks-grounding-for-multi-child-bubbles-option-a)

### 11.1 Problem Statement
When YOLO11 detects connected speech balloons or speech bubbles containing multiple distinct child text regions (`len(bubble.texts) > 1`), `LocalEngine` naturally crops and OCRs each child box separately, producing individual `TranslatedBlock` models. Previously, `CloudEngine` applied only 1 badge at the bubble bounding box center (`bubble.box_2d`), forcing cloud LLMs to translate the entire bubble as 1 single merged string. This broke visual overlay parity with `LocalEngine`.

### 11.2 Fine-Grained Grounding Mechanism
1. **Work Item Granularity:** Instead of placing markers only at bubble centers, `visual_grounding.py` generates badges over `BubbleWorkItem` instances prepared by `src/backend/detection/assembler.py:prepare_local_work_items`.
2. **Strictly Sequential 1-Based Indexing:** Every work item across the page receives a strictly sequential badge: `[1]`, `[2]`, ..., `[M]`. This prevents badge number collisions on manga pages with mixed multi-child and single-child bubbles.
3. **Child Region Outlines:** For bubbles with multiple child texts, a 1px boundary outline is drawn around each child text region (`item.crop_box`) inside the parent bubble contour. Single-child bubbles and pseudo-bubbles (floating narration outside bubbles) receive badges at their outer bounding boxes.
4. **Unified Block Assembly:** The shared `assemble_translated_blocks` maps upstream LLM dictionary responses (`{"1": "...", "2": "..."}`) into distinct `TranslatedBlock` instances, populating `parent_bubble_id=bubble.id`, `parent_box=bubble.box_2d`, and `polygon=bubble.polygon`.
5. **Zero API Contract Changes:** Output JSON conforms identically to `SPEC-api-contract.md`. Frontend (`overlay_manager.ts`) automatically groups blocks under 1 parent polygon mask layer with separate, independently fitted `.inkshift-text-layer` text elements.

