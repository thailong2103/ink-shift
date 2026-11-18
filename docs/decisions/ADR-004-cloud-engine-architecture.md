# ADR-004: Cloud Vision Engine Architecture, Multi-Provider Adapters, and Safety Fallbacks

- **Status:** Accepted
- **Date:** 2026-10-11
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent
- **Target Module:** `cloud-engine` (Module 3 Execution Runtime)
- **Amended By:** [ADR-008](ADR-008-consolidated-engine-architecture-and-shared-detection.md) (Universal Set-of-Marks visual grounding across all providers, ProviderRegistry, and zero-bubble optimization)

---

## 1. Context & Problem Statement

InkShift requires a high-accuracy, single-pass cloud translation provider (`cloud-engine`) to localize raw manga page images into Vietnamese. A single round-trip must accomplish:
1. **Speech Bubble Localization:** Detect visual speech bubbles and text regions, returning bounding boxes normalized to the integer per-mille coordinate space `[0, 1000]` (`[ymin, xmin, ymax, xmax]`) matching the contract defined in [ADR-002](ADR-002-api-contract-and-data-exchange.md).
2. **Context-Aware Translation:** Understand Japanese vertical text (RTL reading flow) or Korean/Chinese manhwa/manhua layouts, generating fluent, natural Vietnamese dialogue with appropriate pronoun conventions.
3. **Multi-Provider & BYOK Flexibility:** Support both official Google AI Studio (Gemini) and third-party gateways like xKiro.com (Qwen models), with a clean architecture that easily accommodates future OpenAI-compatible endpoints (OpenRouter, DeepSeek, local Ollama).
4. **Resilience & Edge Case Defense:** Robustly handle upstream rate limits (HTTP 429), timeouts, empty payloads, and model refusals (content safety/NSFW policy triggers where HTTP status is 200 but text output is refused).
5. **Quality Constraints:** Zero new SDK dependencies (`CONSTRAINTS.md` compliance, utilizing pre-approved `httpx.AsyncClient`), strict types, and $\ge 80\%$ test coverage.

---

## 2. Options Considered

### A. Provider Architecture & Protocol Adapters
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1A: Dual-Provider Adapter Architecture (Selected)** | - Decouples provider wire formats behind `BaseTranslationEngine`.<br>- Supports **Gemini** (Google REST API) and **Universal OpenAI-Compatible** (xKiro, OpenRouter, etc.).<br>- Single interface for the FastAPI coordinator. | - Requires maintaining two request/response serialization adapters. | **Selected (Agent & Human Approved)** |
| **Option 1B: Google AI Studio Direct Only** | - Simplest single-vendor implementation.<br>- Exact 1:1 match with native Gemini `[0, 1000]` coordinate format. | - Locked into Google; no fallback if a user prefers third-party tokens or Qwen models. | Rejected |
| **Option 1C: Third-Party Gateway Only (xKiro / OpenAI only)** | - Single wire protocol. | - Ignores Gemini's superior native structured output guarantees; dependent on aggregator uptime. | Rejected |

---

### B. Primary Model Selection
| Provider | Candidate Models | Selected Model | Rationale |
|---|---|---|---|
| **Google AI Studio** | `gemini-3.8-flash`<br>`gemini-3.5-flash-lite`<br>`gemini-2.0-flash` | **`gemini-3.8-flash`** (Default)<br>*(with `gemini-3.5-flash-lite` option)* | `gemini-3.8-flash` delivers state-of-the-art visual reasoning, superior RTL vertical Japanese manga comprehension, and native `[ymin, xmin, ymax, xmax]` normalized coordinates in $<2.5$s. `gemini-3.5-flash-lite` serves as the high-throughput, low-cost fallback. |
| **xKiro.com / OpenAI-Compatible** | `qwen/qwen3.8-max`<br>`qwen/qwen3.8-flash` | **`qwen/qwen3.8-max`** (Default)<br>*(with `qwen/qwen3.8-flash` option)* | `qwen/qwen3.8-max` exhibits outstanding East Asian character recognition and nuanced manga localization. |

---

### C. Client Integration Technology (HTTP Client vs SDKs)
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 2A: Direct Async REST via `httpx` (Selected)** | - Reuses existing approved `httpx` client in `src/backend`.<br>- Zero new external dependencies (`google-genai`, `openai`).<br>- Full control over timeouts, headers, payload framing, and connection pools. | - Must write lightweight request/response serialization dictionaries manually. | **Selected (Agent & Human Approved)** |
| **Option 2B: Official Vendor SDKs (`google-genai` + `openai`)** | - High-level helper methods. | - Adds $>80$ MB of transitive dependencies.<br>- Increases supply chain attack surface and risk of version conflicts. | Rejected |

---

### D. BYOK & Configuration Lifecycle Strategy
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 3A: Phased Incremental Delivery (Selected)** | - **Phase 1 (Module 3):** Rapid engine delivery using environment configuration (`.env`). Focuses purely on translation quality, coordinate extraction, and error handling.<br>- **Phase 2 (Module 4):** Upgrade to dynamic SQLite multi-key storage and auto-fetch models when implementing the Chrome Extension Settings UI. | - Runtime key switching via web UI is deferred until the Extension UI phase. | **Selected (Agent & Human Approved)** |
| **Option 3B: Monolithic BYOK & CRUD Upfront** | - Complete dynamic key management in Module 3. | - Overengineers backend storage and CRUD APIs before any client UI exists to consume them, stalling progress. | Rejected |

---

### E. Failure Modes & Edge Case Handling Strategy
| Scenario | Detection Mechanism | System Reaction & Recovery |
|---|---|---|
| **Upstream Network Timeout / Hang** | `httpx.Timeout(15.0, connect=5.0)` | Abort request after 15s. Raise `UPSTREAM_TIMEOUT` without blocking server loop. |
| **Rate Limit (HTTP 429)** | Response status code 429 | Exponential backoff with jitter (1s $\to$ 2s, max 2 retries). If still failing, return `RATE_LIMIT_EXCEEDED`. |
| **Auth Failure (HTTP 401/403)** | Response status code 401/403 | No retry. Return structured `INVALID_API_KEY`. |
| **Model Content Refusal (Safety Block)** | Gemini: `finishReason == "SAFETY"` or `BLOCKLIST`.<br>Qwen: Pydantic JSON validation failure + refusal heuristic keywords. | Return structured `CONTENT_SAFETY_BLOCKED`. Suggest user switch to offline `local-engine`. |
| **Empty Image / Empty Page** | Model returns empty block array `[]`. | Valid translation with 0 blocks. Return `TranslationResponse(success=True, blocks=[])`. |

---

## 3. Decision & Rationale

We adopted **Options 1A (Dual-Provider Architecture), 2A (`httpx` Direct REST), 3A (Phased Incremental Delivery), with `gemini-3.8-flash` and `qwen/qwen3.8-max` as primary models**:

1. **Dual-Provider Architecture:** Implement two provider adapters implementing a unified `CloudProvider` protocol:
   - `GeminiProvider`: Targets `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with `responseSchema` (JSON Schema grammar enforcement) and native `[ymin, xmin, ymax, xmax]` normalized coordinates `[0, 1000]`.
   - `OpenAICompatibleProvider`: Targets OpenAI-compatible `/chat/completions` (e.g. `https://api.xkiro.com/v1` for xKiro, OpenRouter, or local Ollama). Employs defensive JSON parsing to strip markdown code blocks and sanitize prompt-instructed JSON.
2. **Composite Engine Registration:** `CloudTranslationEngine` subclasses `BaseTranslationEngine`. It delegates to the active provider selected via configuration (`INKSHIFT_CLOUD_PROVIDER=gemini` or `xkiro`). Both individual providers are also registered as `cloud-gemini` and `cloud-xkiro` for direct per-request routing.
3. **Zero New Dependencies:** Implemented strictly with standard Python libraries and `httpx.AsyncClient`.
4. **Hard Timeout & Retry:** Hard deadline of 15 seconds per cloud vision call; automated exponential backoff retry for HTTP 429 and transient network failures ($\le 2$ retries).
5. **Safety Refusal Interceptor:** Explicitly inspects Gemini `finishReason` and Qwen response content to catch safety filter blocks, formatting them cleanly into `APIErrorResponse` with code `CONTENT_SAFETY_BLOCKED`.

---

## 4. Consequences

- **Positive Impact:**
  - Delivers state-of-the-art vision translation in a single pass without extra OCR steps.
  - 100% mathematical alignment with InkShift's normalized `[0, 1000]` coordinate contract.
  - Zero bloated external SDK dependencies.
  - Supports both Google AI Studio and third-party gateways (xKiro, OpenRouter) out of the box.
  - Fully immune to silent crashes from model safety refusals and upstream rate limits.
- **Trade-offs / Negatives:**
  - Dynamic multi-key CRUD management and auto-fetching model lists are deferred to Module 4 (extension-core settings UI), requiring `.env` configuration during Phase 1.
  - Defensive parsing for Qwen requires robust regex stripping for markdown fences.
- **Follow-up Tasks:**
  - Author specification [docs/specs/SPEC-cloud-engine.md](../specs/SPEC-cloud-engine.md).
  - Define implementation plan in `tasks/plan.md` and checklist in `tasks/todo.md`.
  - Implement `GeminiProvider`, `OpenAICompatibleProvider`, `CloudTranslationEngine`, and unit test suite with mock fixtures.
