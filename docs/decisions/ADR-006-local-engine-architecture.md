# ADR-006: Local Engine Architecture, DirectML Acceleration, Swappable OCR, and Zero-Cost Translation Pipeline

- **Status:** Accepted
- **Date:** 2026-10-15
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent
- **Target Module:** `local-engine` (Module 5 On-Device Translation Engine)
- **Amended By:** [ADR-008](ADR-008-consolidated-engine-architecture-and-shared-detection.md) (Detector decoupled to shared gateway layer; dynamic TranslatorRegistry for Google Translate and LLM Text)
- **Relevant Skills:** `documentation-and-adrs`, `research`, `api-and-interface-design`, `performance-optimization`

---

## 1. Context & Problem Statement

Module 5 (`local-engine`) fulfills the vision established in [CAPABILITY_MAP.md](../specs/CAPABILITY_MAP.md) of providing an independent, **100% free (zero-cost)** on-device manga translation pipeline that runs locally on the user's workstation without requiring external multimodal AI subscriptions or credit cards.

Designing this engine on the developer's hardware presents specific technical challenges and constraints:
1. **Hardware Environment (AMD Ryzen 7 8845HS + Radeon 780M on Windows):** The target system possesses an AMD Zen 4 CPU (8 cores, 16 threads, AVX-512) and an integrated AMD Radeon 780M iGPU (RDNA 3, 12 CUs) with 32GB unified system memory (UMA). Windows does not natively support NVIDIA CUDA; installing heavyweight PyTorch ROCm wheels on Windows consumer APUs is unsupported and unstable.
2. **Detection of Specialized Manga Typography:** Manga typography includes circular/oval bubbles, spiky explosion balloons, text without speech bubbles (floating narration/SFX), and multi-column vertical text. Generic object detectors (e.g. YOLO) often miss borderless text and capture excessive background art.
3. **Linguistic Diversity (Japanese Raw vs. Multilingual Comics):** Japanese manga features complex Kanji, Furigana annotations, and right-to-left vertical text (`tategaki`). In contrast, English comics and Chinese/Korean webtoons feature horizontal or wrapped Latin text with frequent hyphenation (`under-` / `stand`). A single monolithic OCR engine cannot excel across all these scripts without accuracy degradation.
4. **Latency and Memory Footprint:** The engine must keep total end-to-end processing $\le 2.0 - 2.5$ seconds per page. Memory management must leverage the available 32GB RAM effectively, keeping models permanently resident to prevent cold-start reload latency.
5. **Zero-Cost vs. Contextual Quality:** The translation layer must be completely free out-of-the-box (`deep-translator` batch client) while retaining an optional text-only LLM mode that reuses credentials from Module 3 for enhanced literary dialogue nuance.

---

## 2. Options Considered & Architectural Decisions

### A. Hardware Acceleration & Inference Runtime
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1A: Microsoft DirectML via `onnxruntime-directml` (Selected)** | - Hardware-agnostic DirectX 12 acceleration natively supported on AMD Radeon 780M.<br>- Offloads 100% of matrix compute from CPU to iGPU.<br>- Automatic fallback to Zen 4 AVX-512 `CPUExecutionProvider` for unsupported operators.<br>- Lightweight runtime ($<150$MB) without gigabyte-sized CUDA frameworks. | - Operator coverage in DirectML slightly lags CUDA, but all required CNN/ViT operators for manga detection and OCR are fully supported. | **Selected (Agent & Human Approved)** |
| **Option 1B: PyTorch CPU-Only** | - Standard PyTorch ecosystem. | - High CPU utilization; slower latency ($>4$ seconds per page); wastes Radeon 780M iGPU compute. | Rejected |
| **Option 1C: PyTorch ROCm / ZLUDA** | - Claims GPU compute on AMD. | - Unofficial/experimental on Windows for RDNA 3 iGPUs; high probability of driver crashes and complex setup. | Rejected |

---

### B. Text Bubble Detection Model
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 2A: `Comic-Text-Detector` ONNX FP16 (Selected)** | - Specifically trained on manga and comic layouts.<br>- Outputs text line detection, character masks, and **hierarchical line-to-block clustering**.<br>- Accurately segments borderless floating narration and sound effects.<br>- Tiny ONNX footprint (~18MB), executing in ~40–60ms on Radeon 780M. | - Requires post-processing to map polygon contours to axis-aligned $[0, 1000]$ normalized boxes. | **Selected (Agent & Human Approved)** |
| **Option 2B: YOLOv8-manga / YOLOv11** | - Standard rectangular bounding box output. | - Fails on floating text and borderless narration; captures excessive background art in spiky speech balloons; lacks automatic line clustering. | Rejected |
| **Option 2C: CRAFT Text Detector** | - Good general scene text detection. | - Heavy (~80MB); fragments manga text columns; high latency (~300ms). | Rejected |

---

### C. OCR Architecture: Single Composite Engine with Swappable Strategy Adapters
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 3A: Single `LocalTranslationEngine` with `BaseOCREngine` Adapters (Selected)** | - Adheres to DRY and Open/Closed Principle.<br>- Pipeline coordination (detection, cropping, coordinate mapping, translation) is written once.<br>- Specialized adapters: `MangaOCRAdapter` (Japanese raw ViT) and `RapidOCRAdapter` (Multilingual/Latin/Chinese PP-OCRv4).<br>- Clean unit testing of adapters with fixture crops. | - Requires defining abstract contract `BaseOCREngine`. | **Selected (Agent & Human Approved)** |
| **Option 3B: Multiple Independent Engines (`LocalMangaEngine`, `LocalRapidEngine`)** | - No internal strategy pattern needed. | - 85% duplicate code across engines; changes to detection or coordinate math require editing multiple files. | Rejected |

---

### D. Language Routing & User Override Policy
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 4A: Hybrid Model Selection: Explicit Manual Override + Auto Unicode Probe + Chapter Cache (Selected)** | - **Manual Override:** User can explicitly specify `ocr_model: "manga-ocr" | "rapidocr"` in request or popup, bypassing any probe overhead for known manga chapters.<br>- **Auto-Probe Fallback:** If set to `"auto"`, inspects the first bubble with rapid Unicode range checks (Hiragana/Katakana $\to$ `manga-ocr`; Latin/Hanzi $\to$ `RapidOCR`).<br>- **Chapter Cache:** Caches the detected language per chapter URL/tab, ensuring zero re-probe latency on subsequent pages. | - Small routing logic layer in `LocalTranslationEngine`. | **Selected (Agent & Human Approved)** |
| **Option 4B: Pure Automatic Probe on Every Page** | - Fully automated. | - Re-runs probe on every page unnecessarily when reading a 40-page chapter. | Rejected |
| **Option 4C: Pure Manual Selection Only** | - Simplest backend code. | - Degrades user experience for readers who switch between raw manga and English webtoons frequently. | Rejected |

---

### E. Latin Multi-line Text Assembly & De-hyphenation
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 5A: Line Clustering with Regex De-hyphenator (Selected)** | - Vertically sorts lines inside speech bubble (`top-to-bottom`).<br>- Strips trailing hyphens for split words (`dis-` + `appear` $\to$ `disappear`).<br>- Joins regular lines with whitespace, preventing word concatenation bugs (`WHAT ARE` + `YOU DOING` $\to$ `WHAT ARE YOU DOING`). | - Edge case: Compound words intended to keep hyphens (e.g., `spider-man`) are handled via vocabulary/lowercase lookahead heuristics. | **Selected (Agent & Human Approved)** |
| **Option 5B: Naive String Concatenation (`"".join(lines)`)** | - Trivial to implement. | - Severely corrupts English translation; produces garbled text without spaces. | Rejected |

---

### F. Translation Provider Strategy
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 6A: Dual-Provider Swappable Translator (`GoogleFreeTranslator` + `LLMTextTranslator`) (Selected)** | - **Default:** `GoogleFreeTranslator` uses `deep-translator` batch client for instant, 0-cost, $<300$ms translation.<br>- **Optional Pro:** `LLMTextTranslator` sends raw text arrays to Gemini Flash / OpenAI text endpoints, reusing API keys from Module 3.<br>- Text-only tokens cost 50x less than vision tokens and preserve nuanced manga character dialogue. | - Google free endpoint requires external network access. | **Selected (Agent & Human Approved)** |
| **Option 6B: Local Offline LLM Only (Ollama / Qwen2.5)** | - 100% offline. | - Consumes 3-5GB RAM and adds 1.5-2.0s latency; slower for casual reading than fast batch web translation. (Preserved as future optional adapter). | Deferred to Post-MVP |

---

## 3. Decision & Rationale

1. **Hardware Backend:** Standardize on **Microsoft DirectML (`onnxruntime-directml`)** with fallback to `CPUExecutionProvider`. Both `Comic-Text-Detector` and OCR models will execute through DirectML, offloading inference to the AMD Radeon 780M iGPU while utilizing 32GB RAM to keep sessions warm in memory.
2. **Detection Core:** Standardize on **`Comic-Text-Detector` (ONNX FP16, ~18MB)** for manga speech bubble and text block localization.
3. **OCR Core:** Implement **`BaseOCREngine`** with two production adapters:
   - `MangaOCRAdapter`: Based on `manga-ocr-torchless` (ONNX) for raw Japanese manga.
   - `RapidOCRAdapter`: Based on `rapidocr-onnxruntime` (PP-OCRv4 ONNX) for English, Latin scripts, and Chinese Manhua.
4. **Model Selection & Routing:** Support explicit user selection (`ocr_model="manga-ocr" | "rapidocr" | "auto"`), falling back to Unicode range inspection (`\u3040-\u309F` / `\u30A0-\u30FF`) on the first bubble when set to `"auto"`.
5. **Text Post-Processing:** Enforce an automated line assembly and de-hyphenation step before passing extracted text to the translation layer.
6. **Translation Core:** Implement **`BaseTextTranslator`** with `GoogleFreeTranslator` (default zero-cost batch via `deep-translator`) and `LLMTextTranslator` (reusing Module 3 configuration for text-only LLM translation).

---

## 4. Consequences

### Positive Impact
- **Zero API Cost:** Readers can translate thousands of manga chapters without incurring cloud vision costs or entering API keys.
- **Hardware Optimization:** DirectML harnesses the 12 Compute Units of AMD Radeon 780M, delivering sub-1.5s total page latency with zero CPU spikes.
- **Robust Typography:** Japanese vertical Kanji/Furigana and English multi-line wrapped text are both handled accurately by dedicated specialized models.
- **API Contract Compliance:** The local engine implements `BaseTranslationEngine` and returns canonical `TranslationResponse` models with `[0, 1000]` normalized coordinates, requiring zero changes in the Chromium extension.

### Trade-offs & Limitations
- **Model Storage:** The backend requires initial downloading of ONNX weights (~20MB detector + ~180MB manga-ocr + ~15MB RapidOCR = ~215MB total). These will be stored in `.cache/inkshift/models/` and cached permanently.
- **Internet Dependency for Default Translation:** While detection and OCR are 100% offline on-device, `GoogleFreeTranslator` requires an active internet connection to query Google's free translation endpoint. True 100% offline translation via local LLM / NLLB is architectural-ready via `BaseTextTranslator` but deferred to a subsequent enhancement.

### Follow-up Tasks
1. Author formal specification in `docs/specs/SPEC-local-engine.md`.
2. Update `docs/PROJECT_STATE.md` reflecting ADR-006 acceptance.
3. Implement `src/backend/engines/local/` according to the modular adapter architecture.

---

## 5. Architectural Amendments

### Amendment 2026-10-22 (Phase 24: Single-Pass Full-Page RapidOCR & Script-Specialized Routing)
- **Problem:** Benchmark analysis revealed that sequential/batch cropping of 12+ speech bubbles for RapidOCR introduced ~3.5s – 5.0s latency bottleneck for non-Japanese manga/comics (English, Chinese, Korean, Latin).
- **Decision:**
  1. Extended `BaseOCREngine` with `FullPageOCREngine` (`supports_full_page`, `recognize_full_page`).
  2. `RapidOCRAdapter` executes a single inference forward pass across the uncropped page, projects text polygons into YOLO speech bubbles via spatial containment mapping, and sorts multi-line text vertically (`assemble_comic_lines`).
  3. Disabled RapidOCR orientation classifier (`use_cls=False`), eliminating ~750ms overhead with zero quality loss on upright manga dialogue.
  4. Specialized `OCRRouter.recognize_routed_full_page()`: Non-JA bypasses bubble cropping completely; Japanese retains crop-based batching for MangaOCR; auto mode probes via RapidOCR full-page scan (auto-switching to MangaOCR on Japanese Kana detection).
- **Result:** Non-JA OCR latency reduced from ~5.0s to ~430ms–1.2s (7.16x – 10.6x speedup on 2K/4K pages) while preserving 100% Japanese accuracy on MangaOCR.

