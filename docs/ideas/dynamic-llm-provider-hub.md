# Concept One-Pager: Dynamic LLM Provider Hub with Live Model Discovery & Searchable Picker

> **Document:** `docs/ideas/dynamic-llm-provider-hub.md`  
> **Feature Codename:** `dynamic-llm-hub` (Phase 25)  
> **Status:** Refined & Ready for Architecture Spec  
> **Decision-Maker:** Solo Developer (@human)  
> **Origin:** User Ideation (`/idea-refine`) on 2026-10-23  

---

## 1. Problem Statement

InkShift currently supports Google Gemini and OpenAI-compatible xKiro through hardcoded provider logic and fixed model identifiers (`gemini-3.8-flash`, `qwen/qwen3.8-max:free`). This introduces several architectural and user-experience limitations:
1. **Model Rigidity:** When providers launch newer, better, or cheaper models (e.g. Gemini 2.0/2.5 Flash, GPT-4o-mini, Claude 3.5 Sonnet, DeepSeek-V3), users cannot utilize them without manual codebase modifications.
2. **Missing Provider Support:** Anthropic Claude (one of the strongest vision models for complex Asian text & manga typesetting) is not yet supported. Custom OpenAI-compatible endpoints (Groq, OpenRouter, DeepSeek, Local Ollama / LM Studio) cannot be configured with custom base URLs.
3. **Lack of Key Management in UI:** Users must manually edit the backend `.env` file on disk to supply API keys, creating operational friction.
4. **Vision Incompatibility Risk:** In Cloud Vision mode, sending images to text-only models (such as `deepseek-chat` or `o1`) results in immediate HTTP 400 request rejections.
5. **Cluttered Dropdown Navigation:** Providers like OpenRouter or OpenAI return dozens or hundreds of model identifiers; selecting a model without instant search/filtering creates severe usability friction.

---

## 2. Recommended Direction: Unified Dynamic LLM Hub

Implement a **Zero-Hardcode, Live-Discovery LLM Hub** spanning 4 provider tiers, featuring dynamic API key management in Chrome Extension, backend model discovery proxy with vision filtering, and a live searchable model combobox.

### 2.1 The Four Provider Tiers
1. **Google AI:** Official Gemini API (`gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-1.5-pro`...).
2. **OpenAI:** Official OpenAI API (`gpt-4o`, `gpt-4o-mini`, `o1`...).
3. **Anthropic:** Official Claude API (`claude-3-5-sonnet-latest`, `claude-3-5-haiku-latest`...).
4. **Custom (OpenAI-Compatible):** Dynamic Base URL (`{base_url}/v1/models` and `{base_url}/v1/chat/completions`) supporting OpenRouter, DeepSeek, xKiro, Groq, Together AI, or local Ollama / LM Studio.

### 2.2 Live Real-Time Model Fetching (Zero Hardcoding)
- **No static model lists in code:** Every time a user selects a provider or clicks the ↻ Fetch button, the Extension dispatches a request to backend proxy: `POST /api/v1/models/discover`.
- **Backend Proxy Call:** Backend calls the provider's live model catalog endpoint (`GET {base_url}/models` or Google `models.list`) using the user's key. This avoids browser CORS errors and conceals sensitive request headers.
- **Single-Model Persistence:** The Extension **only persists the single active model selected by the user** (`selected_model`) along with credentials in `chrome.storage.local`.
- **Zero Reconfiguration on Next Launch:** When the user reopens the browser or navigates chapters, InkShift automatically loads the saved active model without triggering redundant fetch calls.

### 2.3 Smart Vision Model Filtering
- Each discovered model is tagged with `supports_vision: boolean`.
- In **Cloud Vision Mode (Direct from Image):**
  - Dropdown strictly filters to vision-capable models (e.g. models matching `gemini-*`, `*4o*`, `*vision*`, `*vl*`, `claude-3*`). Text-only models are hidden to eliminate 400 errors.
  - A toggle `[x] Only show Vision models` allows power users using custom Ollama/LM Studio models to disable the heuristic if desired.
- In **Local DirectML Mode (Text Translation post-OCR):**
  - All models (vision and text-only, including DeepSeek-Chat, Llama 3.3, Qwen 2.5) are available since input is raw transcribed text.

### 2.4 Searchable Model Combobox (Live Substring Matching)
- In the Extension Popup, the model selector is upgraded from a static `<select>` to a modern **Searchable Combobox**:
  - Top search input with instant debounced filtering.
  - Substring search: typing `"2"` immediately pushes `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-2.0-pro` to the top.
  - Typing `"sonnet"` or `"haiku"` immediately filters Anthropic models.
  - Clicking an item instantly selects it, closes the dropdown, and saves the selection to `chrome.storage.local`.

### 2.5 Privacy-First Security Model
- Keys are saved in `chrome.storage.local` (isolated per-extension sandbox, unreachable by web pages).
- Keys are transmitted via encrypted local headers (`X-Provider-Key`, `X-Provider-Base-Url`) directly to `http://127.0.0.1:8000`.
- Backend utilizes keys in-memory for the duration of the request only; **keys are never written to disk, database, or log files** (strict compliance with `CONSTRAINTS.md`).

---

## 3. Key Assumptions

1. **API Protocol Conformity:** Major providers adhere to standard model listing endpoints (`/v1/models` for OpenAI/Anthropic/Custom, `v1beta/models` for Google).
2. **Localhost Network Access:** Chrome Extension has permission to send POST requests to `http://127.0.0.1:8000/api/v1/models/discover`.
3. **Dual Pipeline Compatibility:** Both Cloud Vision (`CloudProviderRegistry`) and Local LLM Translator (`TranslatorRegistry`) seamlessly consume dynamic model IDs and keys passed via headers.

---

## 4. MVP Scope & Milestones (Phase 25)

### Milestone 1: Backend Adapters & Model Discovery Proxy
- Implement `AnthropicProvider` implementing `CloudProvider` protocol (`src/backend/engines/cloud/anthropic.py`).
- Enhance `OpenAICompatibleProvider` to support request-scoped `base_url` and `api_key` overrides.
- Implement `POST /api/v1/models/discover` endpoint querying provider model APIs, returning normalized model objects with `id`, `name`, and `supports_vision`.
- Unit tests covering discovery proxy across all 4 provider formats.

### Milestone 2: Request Header Interceptor & Dynamic Registry
- Update `TranslationRequest` and FastAPI endpoints to receive `X-Provider-Key`, `X-Provider-Base-Url`, `X-Provider-Model`.
- Inject client credentials dynamically into `CloudProviderRegistry` and `TranslatorRegistry` execution pipelines.

### Milestone 3: Extension Popup Key Management & Searchable Combobox
- Add collapsible **`AI Providers & API Keys`** drawer in `popup.html`.
- Tabbed provider switcher: `[Google]` | `[OpenAI]` | `[Anthropic]` | `[Custom / OpenAI-Base]`.
- Masked password input for API Keys + Base URL input for Custom tier.
- Searchable Model Combobox with live substring filtering and vision capability badge (`[Vision]`).
- Persistence in `chrome.storage.local`: auto-load saved active model without re-fetching.

---

## 5. What We Are NOT Doing (Explicit Non-Goals)

1. **No Backend Database Key Storage:** We will NOT store user API keys in SQLite or server databases to avoid data breach risks and privacy liability.
2. **No Hardcoded Model Fallback Arrays:** We will NOT maintain static model catalogs in frontend code; models must be dynamically fetched live from provider accounts.
3. **No Complex Billing/Token Tracking Dashboard:** InkShift is a lightweight manga translator, not an API billing portal.
4. **No Direct Extension-to-Provider Calling:** All external API requests route through the local FastAPI backend to bypass browser CORS headers, maintain unified request retries, and ensure single-point observability.
