# ADR-008: Consolidated Engine Architecture, Shared Gateway Detection, and Dynamic Registries

- **Status:** Accepted
- **Date:** 2026-10-17
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** AI Agent
- **Target Modules:** `backend-engine`, `cloud-engine`, `local-engine`, `detection`, `api-contract`, `extension-core`
- **Amends:** [ADR-003](ADR-003-backend-engine-architecture.md), [ADR-004](ADR-004-cloud-engine-architecture.md), [ADR-006](ADR-006-local-engine-architecture.md), [ADR-007](ADR-007-yolo11-manga-detection-and-visual-grounding.md)
- **Relevant Skills:** `documentation-and-adrs`, `api-and-interface-design`, `performance-optimization`, `constraint-driven-development`

---

## 1. Context & Problem Statement

Following the delivery of Module 5 (`local-engine`) and ADR-007 (YOLO11s-seg + Set-of-Marks), the InkShift engine ecosystem suffered from architectural fragmentation and combinatorial bloat:

1. **Combinatorial Engine Sprawl:** The backend registered up to 7 distinct engine names (`local`, `local-rapidocr`, `local-manga-ocr`, `cloud`, `cloud-gemini`, `cloud-openai`, `mock`). This leaked internal implementation details to the extension client and made client-side engine switching cluttered and error-prone.
2. **Detection Logic Duplication & Inverted Dependency:** YOLO11 bubble segmentation was trapped inside `src/backend/engines/local/detector/`. Cloud engine required bubble detection for Set-of-Marks (SoM) visual grounding, forcing cloud components to import directly from a peer engine (`local`), violating clean modular boundaries.
3. **Cloud Provider Disparity:** While `GeminiProvider` implemented Set-of-Marks visual grounding (18–25 polygon vertices + numerical badge prompt), OpenAI-compatible providers lacked visual grounding parity, incurring high token costs and coordinate drift.
4. **Cache Key Collision Risk:** The SQLite translation cache keyed entries solely on `(image_hash, target_lang)`. Translating a page with `local` (OCR + Google Translate) cached a result that was subsequently served when the user requested `cloud` (LLM translation), preventing comparison or quality switching.
5. **Rigid Translator Configuration:** `LocalTranslationEngine` coupled text translation directly to `GoogleFreeTranslator` without dynamic runtime selection or swappable LLM text translation.

---

## 2. Options Considered & Architectural Decisions

### A. Engine Consolidation & Abstraction Hierarchy
| Option | Description | Pros | Cons | Decision |
|---|---|---|---|---|
| **Option 1A: 2 Canonical Engines + Testing Mock (Selected)** | Collapse public engine registry to `"local"`, `"cloud"`, and `"mock"`. Sub-components selected via dynamic query/body parameters (`provider`, `translator`). | Clean mental model; extensible via registries; minimal UI clutter in Chrome extension. | Extension popup requires secondary dropdowns for fine-grained tuning. | **Selected (Agent & Human Approved)** |
| **Option 1B: Flat Enumerated Engines (Baseline)** | Retain separate engines for every permutation (`local-google`, `local-llm`, `cloud-gemini`, `cloud-openai`, etc.). | Simple flat string matching. | Combinatorial explosion (2 engines × 2 providers × 2 translators = 8+ engines); brittle UI. | Rejected |

---

### B. Shared Detection Architectural Placement
| Option | Description | Pros | Cons | Decision |
|---|---|---|---|---|
| **Option G1: Gateway-Level Detection (Selected)** | Extract YOLO11 into standalone `src/backend/detection/`. FastAPI endpoint (`translate.py`) runs detection once on un-cached requests for `local` and `cloud`, passing pre-sorted bubbles into `engine.translate()`. | Eliminates redundant detection; guarantees 100% detection consistency across all engines; zero engine-to-engine coupling. | Engines must accept `bubbles: list[DetectedBubble]` in their method contracts. | **Selected (Option G1 Approved)** |
| **Option G2: Engine-Internal Delegation** | Each engine independently invokes the shared detector if bubbles are not provided. | Keeps API gateway thinner. | Logic duplication across engine wrappers; harder to optimize gateway cache checks. | Rejected |
| **Option G3: Direct Extension Pipeline** | Extension requests detection in a separate HTTP call before requesting translation. | Client orchestrates pipeline stages. | Extra network roundtrips over HTTP; high browser IPC serialization overhead. | Rejected |

---

### C. Universal Cloud Set-of-Marks (SoM) Parity
- **Decision:** All cloud providers implementing the `CloudProvider` protocol (`GeminiProvider`, `OpenAICompatProvider`) utilize the shared `src/backend/engines/cloud/visual_grounding.py` module.
- **Set-of-Marks Flow:**
  1. Backend receives pre-sorted `bubbles` from the gateway.
  2. If `bubbles == []`, return empty translated blocks immediately (**Zero-bubble optimization: 0 tokens, 0 network latency, 0 cost**).
  3. Visual grounding draws 1px bounding outlines and black-on-white numeric badge identifiers `[1], [2]...` onto the manga image.
  4. Provider sends marked image to the upstream LLM with a concise system prompt requesting a flat JSON dictionary `{"1": "...", "2": "..."}`.
  5. Extracted text is re-associated with YOLO11's polygon masks and safe-zone boxes.

---

### D. Dynamic Registries for Providers and Translators
- **Cloud Provider Registry (`src/backend/engines/cloud/provider_registry.py`):**
  - Manages `gemini` and `openai` (or custom endpoint names) conforming to `CloudProvider`.
  - Resolves provider by name, falling back to configured default.
- **Local Translator Registry (`src/backend/engines/local/translator/registry.py`):**
  - Manages `google-free` (`deep-translator`) and `llm-text` (`OpenAICompatTextTranslator`) conforming to `BaseTextTranslator`.
  - Supports dynamic runtime switching via `translator` request parameter.

---

### E. Cache Schema Isolation
- **Composite Primary Key:** Upgrade `translation_cache` table in `src/backend/cache/sqlite_cache.py`:
  ```sql
  PRIMARY KEY (image_hash, target_lang, engine_used)
  ```
- **Isolation Guarantee:** Translations produced by `local` and `cloud` exist in distinct cache slots, allowing users to alternate between engines on the same manga page without cache collisions.

---

## 3. Consequences

### Positive:
1. **Simplified Client & Clean UI:** The Chrome extension popup presents a clean, intuitive choice between `Auto`, `Local DirectML`, and `Cloud AI`, with contextual sub-selectors appearing only when relevant.
2. **Zero Redundant Work:** Detection runs exactly once per uncached page translation regardless of engine.
3. **100% Type & Quality Gate Compliance:** Strict mypy, ruff, and zero-suppression (`Floor Guard`) standards maintained across all 48 source files.
4. **Enhanced Test Coverage:** Full suite of 212 backend tests and 93 extension tests pass with 88.44% backend coverage ($\ge 80\%$ required).

### Negative / Migrations Handled:
1. **Database Migration:** Existing `data/cache.db` files migrate automatically to include `engine_used` column with index rebuild.
2. **Backward Compatibility:** Requests omitting `provider` or `translator` automatically resolve to configured defaults from `Settings`.

---

## 4. Addendum: Fine-Grained Set-of-Marks Grounding for Multi-Child Bubbles (Option A)

- **Date:** 2026-10-18
- **Decision-Maker:** Solo Developer (@human)
- **Status:** Accepted

### A. Context & Parity Gap
In manga pages with connected speech balloons or bubbles containing multiple dialogue text lines (`len(bubble.texts) > 1`), `LocalEngine` independently cropped and OCR-processed each child text region, generating individual `TranslatedBlock` models with `parent_box` and `parent_bubble_id` linking.
Conversely, `CloudEngine` visually grounded 1 badge per bubble center, returning 1 merged string and 1 single block for the entire bubble, causing font-fitting and overlay discrepancies.

### B. Options Considered
| Option | Description | Pros | Cons | Decision |
|---|---|---|---|---|
| **Option A: Fine-Grained SoM on Work Items (Selected)** | Annotate individual child text regions with strictly sequential 1-based badges `[1]`, `[2]`, ... across all `BubbleWorkItem`s. Upstream LLM returns flat JSON `{"1": "...", "2": "..."}`. | Full multimodal vision parity; 1:1 identical block structure with LocalEngine; 0 local OCR dependency. | Slightly more visual marks drawn on complex pages. | **Selected (Agent Proposed & Human Approved)** |
| **Option B: Bubble Badge + JSON Array Mapping** | Keep 1 badge per bubble, prompt LLM to return `{"1": ["text 1", "text 2"]}`. | Fewer marks on image. | Fragile: LLMs frequently misalign array length with child text count; JSON parsing errors. | Rejected |
| **Option C: Hybrid Local OCR + Cloud Text Translation** | Local OCR reads text lines; Cloud LLM translates pure text strings. | High text precision. | Loses visual context (speaker emotion, font style); requires running heavy local OCR models in cloud mode. | Rejected |

### C. Consequences
1. **1:1 Structural Engine Parity:** `LocalEngine` and `CloudEngine` emit identical `TranslatedBlock` structures for all bubble topologies.
2. **Deterministic Lookup:** Sequential `idx + 1` badge numbers prevent ID collisions on mixed pages.
3. **Zero API Contract Breaking Changes:** Schema remains 100% stable; client overlay renderer (`overlay_manager.ts`) automatically groups blocks under 1 polygon mask layer.

