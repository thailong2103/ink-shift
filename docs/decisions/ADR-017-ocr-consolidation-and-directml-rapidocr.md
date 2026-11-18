# ADR-017: OCR Pipeline Consolidation and DirectML RapidOCR Standardization

- **Status:** Accepted
- **Date:** 2026-10-26
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

In the initial architecture ([ADR-006](ADR-006-local-engine-architecture.md)), the local inference engine was designed with a dual-OCR adapter strategy:
1. `MangaOCRAdapter`: Intended for raw Japanese manga dialogue using an ONNX or PyTorch vision-encoder-decoder transformer (`manga-ocr`).
2. `RapidOCRAdapter`: Intended for multilingual, Latin, and Chinese text recognition using PP-OCRv4 via ONNX Runtime DirectML.

However, subsequent real-hardware profiling and technical investigations revealed three critical impediments:
1. **Hardware Incompatibility with PyTorch CUDA:** The target host hardware is powered by AMD Ryzen APUs with integrated **AMD Radeon 780M graphics** (supporting DirectX 12 and DirectML, but lacking NVIDIA CUDA). Standard PyTorch falling back to CPU execution requires **24.6 seconds** per manga page (13 bubbles), saturating CPU cores and generating high thermal load.
2. **Memory Ceiling Violation:** Full PyTorch + HuggingFace transformer weights require $>1.5\text{ GB}$ of RAM, severely threatening the $2048\text{ MB}$ maximum memory ceiling mandated by [CONSTRAINTS.md](../../CONSTRAINTS.md).
3. **Incomplete ONNX Stub & Crash in Production:** The `MangaOCRAdapter` in `src/backend/engines/local/ocr/manga_ocr.py` was an incomplete stub (calling a single `onnxruntime.InferenceSession` on a vision sequence-to-sequence model lacking tokenization and autoregressive decoding). Whenever a reader selected "Ngôn ngữ gốc: Tiếng Nhật (Manga)" (`source_lang="ja"`) in the browser extension popup, `OCRRouter` routed explicitly to `MangaOCRAdapter`, immediately throwing `RuntimeError: Failed to initialize MangaOCR engine` and failing with HTTP 500 (`ENGINE_EXECUTION_FAILED`).

Meanwhile, `RapidOCR` (PP-OCRv4 ONNX accelerated via Microsoft DirectML) executes natively on the AMD Radeon 780M iGPU in **$\sim500\text{ ms}$ for the entire page**, has a tiny footprint ($\sim15\text{ MB}$ disk, $\sim100\text{ MB}$ RAM), and natively transcribes Japanese Kanji, Hiragana, and Katakana alongside Latin, Korean, and Chinese scripts.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Full PyTorch MangaOCR Installation**<br>(Install PyTorch CPU + `manga-ocr` pip package via setup script) | - High accuracy on stylized vertical Japanese text and furigana. | - Adds $\sim750\text{ MB}$ download / $1.8\text{ GB}$ disk space.<br>- Incurs 20–25s latency per page on CPU.<br>- Exceeds 2048 MB memory constraint. | Not Recommended |
| **Option 2: Consolidate on DirectML RapidOCR (Selected)**<br>(Standardize all OCR routing on `RapidOCRAdapter`, purge `manga_ocr.py` stub) | - Sub-second latency ($\sim500\text{ ms}$) on AMD Radeon 780M iGPU.<br>- Uses $<150\text{ MB}$ RAM, adhering to [CONSTRAINTS.md](../../CONSTRAINTS.md).<br>- Eliminates HTTP 500 crash when `source_lang="ja"` is selected.<br>- Removes dead code, simplifying maintenance. | - Slightly lower accuracy on heavily stylized vertical text compared to full ViT. | **Selected (Agent & Human Approved)** |
| **Option 3: Soft Deprecation with Fallback**<br>(Keep `manga_ocr.py` stub, but force router fallback to RapidOCR) | - Retains the stub for future potential eGPU users. | - Leaves non-functional code in production repository.<br>- Causes confusion for future contributors. | Not Recommended |

---

## 3. Decision & Rationale

1. **Standardize on DirectML RapidOCR:** All OCR requests (`ja`, `japanese`, `manga-ocr`, `en`, `ko`, `zh`, and `auto`) are consolidated to execute through `RapidOCRAdapter` utilizing Microsoft DirectML (`onnxruntime-directml`) on DirectX 12 hardware, with automatic CPU fallback.
2. **Purge Non-Functional MangaOCR Stub:** Remove `src/backend/engines/local/ocr/manga_ocr.py`, remove its export in `__init__.py`, and remove `inkshift_local_manga_ocr_model_path` in `src/backend/config.py`.
3. **Amend ADR-006:** Update ADR-006 to reflect that the dual-OCR strategy is superseded by single-engine DirectML RapidOCR consolidation.
4. **Resilient Extension Handling:** When readers select "Tiếng Nhật (Manga)" (`source_lang="ja"`) in the extension popup, `OCRRouter` routes directly to `RapidOCRAdapter`, returning HTTP 200 with transcribed and translated speech bubbles.

---

## 4. Consequences

### Positive Impact
- **Zero Crashes on Japanese Selection:** Readers can select "Tiếng Nhật (Manga)" without triggering `ENGINE_EXECUTION_FAILED`.
- **Sub-Second Performance:** Japanese manga translation latency drops from $>24\text{ s}$ to $<1.5\text{ s}$ total pipeline latency on AMD Radeon 780M hardware.
- **Resource Compliant:** Memory consumption remains well below the $2048\text{ MB}$ ceiling.
- **Codebase Simplicity:** Eliminates mock-only unit tests and removes $\sim200$ lines of dead code and obsolete settings.

### Trade-offs / Negatives
- Vertical furigana or artistic handwritten SFX will rely on RapidOCR's character grouping rather than specialized manga-only ViT generation.

### Follow-up Tasks
1. Amend [ADR-006](ADR-006-local-engine-architecture.md).
2. Update Living Spec [docs/specs/SPEC-local-engine.md](../specs/SPEC-local-engine.md).
3. Update [docs/PROJECT_STATE.md](../PROJECT_STATE.md) index table.
4. Refactor `OCRRouter` in `src/backend/engines/local/ocr/router.py`.
5. Remove `src/backend/engines/local/ocr/manga_ocr.py` and update config/exports.
6. Modernize unit tests and add regression test for Japanese translation.
