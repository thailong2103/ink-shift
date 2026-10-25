# ADR-012: Dynamic LLM Provider Hub (4 Tiers, Live Discovery Proxy, and .env Key Management)

- **Status:** Accepted
- **Date:** 2026-10-23
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** Antigravity AI Agent
- **Related Spec / Feature:** Phase 25 (`docs/specs/SPEC-dynamic-llm-hub.md`, `docs/specs/SPEC-cloud-engine.md`, `docs/specs/SPEC-api-contract.md`)

---

## 1. Context & Problem Statement

InkShift previously relied on hardcoded model identifiers (`gemini-3.8-flash` in `src/backend/config.py` and `qwen/qwen3.8-max:free` for xKiro) rendered through static HTML `<select>` options. This presented several operational bottlenecks:
1. **Model Staleness:** Rapid evolution in the LLM ecosystem (e.g., `gemini-2.5-flash`, `gpt-4o-mini`, `claude-3-5-sonnet`) left the UI outdated, requiring code modifications to access newer, cheaper, or faster models.
2. **Limited Provider Coverage:** Support was restricted to Google Gemini and an ad-hoc xKiro/OpenAI proxy. Leading models like Anthropic Claude were not supported as first-class providers.
3. **Configuration Friction:** Users had to manually edit `.env` on disk and restart the backend server to configure keys or switch between local endpoints (e.g., Ollama) and cloud providers.
4. **Credential Security Risk:** Persisting raw API keys inside the browser extension's `chrome.storage.local` creates exposure risks to extension sandbox inspection and complicates multi-machine setups.

We required a standardized, secure, and future-proof LLM hub that decouples model discovery from hardcoded code, supports the four major provider ecosystems, and enables seamless in-extension configuration.

---

## 2. Options Considered

### Part A: Credential Storage & Source of Truth

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A: Extension `chrome.storage.local`** | - Pure client-side storage.<br>- No backend write mechanism required. | - Vulnerable if browser profiles sync across machines.<br>- Difficult to manage for local headless scripts.<br>- Inconsistent with backend service worker architecture. | Rejected |
| **Option B: Windows Credential Manager (DPAPI)** | - Hardware-backed encryption via Windows DPAPI.<br>- High protection against local process theft. | - Platform lock-in (breaks Linux/macOS portability).<br>- Requires external C-bindings/binaries.<br>- Inconvenient to inspect or backup. | Rejected |
| **Option C: Local `.env` File (Backend Single Source of Truth)** | - Unified source of truth across all tools.<br>- Easy to back up, inspect, and migrate.<br>- Protected by `.gitignore` and `gitleaks`.<br>- Extension acts purely as control panel via authenticated API. | - Requires atomic file swap mechanism on backend.<br>- Keys stored as plaintext on developer's local filesystem. | **Accepted (Chosen by Developer)** |

### Part B: Model Catalog Management

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Static Hardcoded Model Lists** | - Zero network overhead on popup opening.<br>- Guaranteed known model compatibility. | - Models quickly become obsolete.<br>- Requires ongoing codebase patches.<br>- Cannot discover custom models on Ollama/vLLM. | Rejected |
| **Option 2: Direct Frontend Fetch from Upstream APIs** | - Completely bypasses backend server. | - CORS blocks browser requests to Google/Anthropic.<br>- Exposes raw API keys in browser network tab.<br>- Requires duplicate HTTP clients in TypeScript. | Rejected |
| **Option 3: Live Discovery Proxy via Backend + Smart Filtering** | - Zero hardcoded model catalogs anywhere.<br>- Backend proxies requests, avoiding CORS and credential leaks.<br>- Tags multimodal/vision capability dynamically.<br>- 5-minute server-side caching avoids rate limits. | - Requires backend to be online to discover new models. | **Accepted (Recommended)** |

---

## 3. Decision & Rationale

The solo developer decided to implement the **Dynamic LLM Provider Hub** based on **Option C (.env Single Source of Truth)** and **Option 3 (Live Discovery Proxy + Smart Filtering)**:

1. **Four Canonical Provider Tiers:**
   - **Google Gemini:** Official Google AI Studio API (`v1beta/models`).
   - **OpenAI:** Official OpenAI API (`api.openai.com/v1/models`).
   - **Anthropic Claude:** Official Anthropic Messages API (`api.anthropic.com/v1/models`).
   - **Custom (OpenAI-Compatible):** Configurable base URL (targeting DeepSeek, Groq, OpenRouter, local Ollama, LM Studio).
2. **Zero-Hardcoding Live Discovery:**
   - Endpoint `POST /api/v1/models/discover` queries upstream catalog APIs live.
   - Categorizes models and tags `supports_vision: bool`.
   - In Cloud AI mode, extension combobox strictly displays vision-capable models. In Local DirectML mode, all text models are selectable.
3. **Atomic `.env` Persistence & In-Memory Reload:**
   - Dedicated `src/backend/security/env_manager.py` writes updates via `.env.tmp` followed by atomic replacement.
   - Updates `os.environ` and `app.state.settings` dynamically without restarting the FastAPI server.
   - Endpoint `GET /api/v1/settings/providers` returns masked keys (`AIzaSy...4xK8`) for UI display.
4. **Searchable Combobox & Single-Model Persistence:**
   - Replaces `<select>` with a live substring search combobox.
   - Extension persists only `selected_model` per provider in `chrome.storage.local`.
   - On popup launch, the active model is restored immediately with 0ms network latency; catalog fetching is lazy and on-demand.
5. **Strict Backward Compatibility:**
   - Retains aliases `xkiro` -> `custom`, `cloud-gemini` -> `google`, `llm-qwen` -> `custom`, `llm-gemini` -> `google`.
   - Preserves all existing test suites without regression.

---

## 4. Consequences

### Positive Impact
- **Future-Proof:** Newly released LLMs (e.g. Gemini 2.5, Claude 3.7) become available immediately without any code changes.
- **Enhanced Manga Nuance:** Anthropic Claude joins the roster, providing top-tier conversational and literary manga translations.
- **Convenience:** Users configure API keys and custom endpoints directly inside the browser extension popup.
- **Safe from Regressions:** Strict smart filtering prevents non-vision models from crashing Cloud translation.

### Trade-offs & Accepted Complexities
- **Backend Dependency:** Live model discovery requires the local FastAPI backend to be running. (Mitigated: selected model is cached in extension storage, allowing reading to continue if model was already chosen).
- **Custom Model Heuristics:** Open-source model catalogs may lack standard multimodal flags. (Mitigated: keyword heuristic matching on `vl`, `vision`, `multimodal`, `qwen2.5-vl`, etc.).

---

## 5. Implementation Roadmap
- **Phase 1:** Backend Provider Adapters (`AnthropicProvider`, generalized `OpenAICompatibleProvider`, `env_manager.py`).
- **Phase 2:** FastAPI Discovery & Settings Routers (`POST /models/discover`, `GET/POST /settings/providers`).
- **Phase 3:** Request Propagation (`TranslationRequest.model` across Cloud and Local engines).
- **Phase 4:** Chrome Extension Searchable Combobox & Key Drawer with defensive UX error handling.
- **Phase 5:** End-to-end verification, Floor Guard compliance (0 suppressions), and test suite expansion.
