# ADR-018: Multilingual DirectML OCR Model Pool, Inverted Baseline Probing, and Language Routing

- **Status:** Superseded by ADR-019
- **Date:** 2026-11-02
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

Following the OCR consolidation in [ADR-017](ADR-017-ocr-consolidation-and-directml-rapidocr.md), all local OCR operations ran on `RapidOCRAdapter` utilizing `onnxruntime-directml`.  
Code audit revealed a critical limitation:
1. The bundled PP-OCRv4 model in `rapidocr_onnxruntime` (`ch_PP-OCRv4_rec_infer.onnx`) is specialized for Simplified Chinese and Latin/English. Its 6,625-character CTC dictionary contains **0 Korean Hangul characters** and only **1 Japanese Hiragana and 4 Katakana characters**.
2. As a consequence, Japanese dialogue lost 99% of Kana particles and Korean manhwa OCR failed completely with empty text strings.
3. The Extension Popup's `#source-lang-select` (`ja`, `ko`, `zh`, `en`, `auto`) was functional over IPC and network, but was a no-op inside `OCRRouter` because both Japanese and non-Japanese branches mapped to the same Chinese model.
4. Furthermore, the legacy `auto` probe suffered from a "Chicken-and-Egg Paradox": probing with a Chinese-only OCR model could never produce Kana or Hangul in the output string, causing character regex checks to fail permanently and falsely conclude that the text was not Japanese or Korean.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: On-Demand Plug & Unplug ("Cắm rút")**<br>Load requested ONNX model from disk and unload previous session on each request. | - Minimizes idle RAM usage (only 1 model loaded at any point). | - Creating a DirectML `InferenceSession` on Windows DirectX 12 incurs 500ms–1200ms shader compilation latency.<br>- Each switch causes an intolerable ~1s freeze on reader pages.<br>- Risk of DirectX 12 driver handle fragmentation. | Not Recommended |
| **Option 2: Reintroduce PyTorch MangaOCR**<br>Reinstall PyTorch CPU + `manga-ocr` for Japanese. | - High accuracy on stylized vertical Japanese text. | - Re-adds ~1.8GB download and >1.5GB RAM usage, violating [CONSTRAINTS.md](../../CONSTRAINTS.md).<br>- Extreme CPU latency (20-25s/page on AMD 780M without CUDA). | Rejected (Superseded by ADR-017) |
| **Option 3: DirectML ONNX Model Pool with Lazy-Loading & Inverted Baseline Probing (Selected)**<br>Maintain a dictionary pool of specialized ONNX recognition models (`japan_PP-OCRv3_rec`, `korean_PP-OCRv3_rec`, `ch_PP-OCRv4_rec`) under DirectML GPU acceleration. | - Sub-second latency (<500ms) on AMD 780M iGPU across Japanese, Korean, Chinese, and English.<br>- Total model weights across all 3 languages is <40MB disk and <50MB VRAM.<br>- Lazy-loading initializes a model once on first request; subsequent switches between languages incur **0 ms latency**.<br>- Resolves the Chicken-and-Egg paradox: Japanese model contains Kana + Kanji + Latin, serving as an effective multi-script baseline probe. | - Requires managing download and caching of ~11MB ONNX files and dictionary `.txt` files for Japanese and Korean. | **Selected (Agent & Human Approved)** |

---

## 3. Decision & Rationale

The developer approved **Option 3: DirectML ONNX Model Pool with Lazy-Loading & Inverted Baseline Probing**.

Key factors driving the decision:
1. **0ms Switching Overhead:** Once loaded, switching between Japanese manga, Korean manhwa, and Chinese manhua occurs instantly without DirectML session re-creation.
2. **Minimal Resource Footprint:** Total VRAM overhead for all 3 models is under 50 MB, adhering strictly to the <2048 MB memory constraint in `CONSTRAINTS.md`.
3. **Resolution of Chicken-and-Egg Paradox:**
   - If user explicitly selects language in popup (`ja`, `ko`, `zh`, `en`), bypass probing completely and dispatch directly to the specialized model.
   - If user selects `auto`:
     - Prioritize Site Adapter metadata (e.g. Hitomi/MangaDex language tags in URL/DOM).
     - Otherwise, probe single dialogue bubble using Japanese model (which covers Kana, Kanji, and Latin) or check candidate confidence scores, then cache the result in `_chapter_cache`.
4. **Resilient Offline Fallback:** If specialized weights are missing and download is unavailable, the engine gracefully logs `ModelDownloadFallback` and uses the default model, preventing HTTP 500 crashes.

---

## 4. Consequences

- **Positive Impact:**
  - True end-to-end OCR accuracy for Japanese Manga and Korean Manhwa offline on consumer hardware.
  - The Extension Popup language selector is fully functional down to the neural inference layer.
  - Retains DirectML GPU acceleration with zero heavy dependencies (no PyTorch, no CUDA required).
- **Trade-offs / Negatives:**
  - Initial run on Japanese or Korean requires downloading ~11MB ONNX weights and dictionary files if not pre-cached.
- **Follow-up Tasks:**
  - Implement Tasks 42.1 to 42.10 in [tasks/todo.md](../../tasks/todo.md).

