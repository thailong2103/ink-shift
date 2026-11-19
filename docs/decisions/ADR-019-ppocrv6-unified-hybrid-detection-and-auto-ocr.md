# ADR-019: Unified Hybrid Layout Detection (`YOLO11s-seg` + `PP-OCRv6_medium`), Bi-Directional Auto-OCR, and Removal of Manual Mode/Language Controls

- **Status:** Accepted (Supersedes ADR-018)
- **Date:** 2026-11-19
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

Practical field testing of the local engine pipeline revealed four architectural limitations stemming from ADR-017 and ADR-018:
1. **Manual Dual-Mode Friction (`Manga | Văn bản`):** Pages containing both speech bubbles and floating/narrative prose paragraphs forced users to toggle between `Manga` (YOLO11 only, which fragmented prose paragraphs via orphan pseudo-bubbles) and `Văn bản` (DBNet only, which lost curved balloon polygons).
2. **Legacy OCR Dictionary Blind Spots:** Bundled `ch_PP-OCRv4_rec_infer.onnx` lacked Japanese Kana, while `japan_PP-OCRv3_rec_infer.onnx` lacked frequent Simplified Chinese characters (`这`, `们`, `说`, `吗`, `你`), causing inverted baseline probing failures and broken cross-script pages.
3. **Horizontal-Only Line Assembly:** `RapidOCRAdapter` sorted all lines inside bubbles and `cluster_lines_to_paragraphs()` strictly top-to-bottom / left-to-right, scrambling vertical Right-to-Left (RTL) Japanese manga and vertical Chinese manhua columns, and accidentally concatenating Japanese furigana.
4. **Manual Source Language Selector Friction:** Keeping a manual `#source-lang-select` dropdown and `#reader-mode-toggle` in the extension popup forced users to reconfigure settings whenever switching between manga, manhua, manhwa, Western comics, or prose pages.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A (Selected): Unified Hybrid `YOLO11s-seg` + `PP-OCRv6_medium` (`rapidocr>=3.9.1`) + Auto-Detection** | - Single `PP-OCRv6_rec_medium` model (18,708 embedded chars) covers Simplified/Traditional Chinese, Japanese Kanji/Hiragana/Katakana, and English/Latin in 1 pass (~85.7ms DirectML on AMD Radeon 780M).<br>- Keeps YOLO11s-seg (~63.1ms DirectML) for smooth Chaikin RDP curved bubble polygons & SFX exclusion mask.<br>- Fuses residual non-bubble, non-SFX DBNet lines (`PP-OCRv6_det_medium`, ~178.3ms DirectML) into cohesive horizontal/vertical prose clusters in the same pass.<br>- Zero-PyTorch ONNX Runtime DirectML (~260ms total GPU inference), strict compliance with `<2048 MB` memory ceiling.<br>- Eliminates manual `reader_mode` & `sourceLang` popup controls cleanly. | - `PP-OCRv6_rec_medium` has 0 Korean Hangul characters, requiring lazy fallback to `korean_PP-OCRv5_rec_mobile.onnx` (~13.5 MB).<br>- Requires bypassing `rapidocr==3.9.1` OmegaConf `DictConfig` DirectML provider bug via explicit `ort.InferenceSession` injection. | **Recommended & Accepted by Developer.** |
| **Option B: `comic-text-detector` + PyTorch `MangaOCR`** | - High Japanese accuracy on stylized furigana-heavy bubble art. | - Requires PyTorch (~1.5–2 GB overhead), poor Chinese/Korean support, slow CPU/DirectML latency. | Rejected (violates lightness & DirectML constraints). |
| **Option C: `PP-OCRv6_small` / `PP-OCRv5_mobile`** | - Faster (~49.8ms det + ~29.7ms rec on DirectML). | - Lower accuracy on dense stylized manga fonts and tight CJK columns compared to `PP-OCRv6_medium`. | Rejected (`medium` comfortably meets latency budget with higher accuracy). |

---

## 3. Decision & Rationale

The developer approved **Option A (`PP-OCRv6_medium`)** AND chose to **remove both manual `Ngôn ngữ gốc` (`sourceLang`) and `Chế độ đọc` (`reader_mode`) controls** so layout, orientation, and OCR script detection operate 100% automatically:

1. **Dependency & Model Stack (`rapidocr>=3.9.1`):**
   - Replace `rapidocr-onnxruntime` with `rapidocr>=3.9.1` while retaining `onnxruntime-directml>=1.17.0`.
   - Provision `PP-OCRv6_det_medium.onnx` (62.1 MB) and `PP-OCRv6_rec_medium.onnx` (76.6 MB, embedded `character` ONNX metadata) from ModelScope RapidOCR v3.9.1 release.
   - Lazy-load `korean_PP-OCRv5_rec_mobile.onnx` (13.5 MB) when Korean Hangul is detected or suspected (low `PP-OCRv6` confidence / high empty crop ratio without Kana).
2. **DirectML Provider Bug Workaround:**
   - Pre-construct `ort.InferenceSession(..., providers=[("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"])` in InkShift and inject it into `rapidocr`'s `TextDetector` / `TextRecognizer` sessions, bypassing `ProviderConfig.dml_ep_cfg()` OmegaConf `DictConfig` serialization error.
3. **Unified Hybrid Layout & Bi-Directional Geometry:**
   - `YOLO11Detector.detect_full_layout()` returns real speech bubbles (sorted by 2-tier RTL `MangaReadingOrderSorter`), panels, and NMS-filtered `sfx_boxes` WITHOUT synthesizing fragmented pseudo-bubbles from orphan text.
   - `OCRRouter.recognize_hybrid_page()` runs single-pass `PP-OCRv6_det_medium` (`unclip_ratio=1.8, box_thresh=0.35, thresh=0.2, limit_side_len=1920`), routes boxes into Bucket A (inside bubbles) and Bucket B (residual outside bubbles & outside SFX boxes with IoA < 0.40), filters vertical Furigana, crops once (`get_rotate_crop_image`), runs 1-pass `PP-OCRv6_rec_medium` (+ auto Korean fallback reusing crops, cached per chapter), applies an ambiguous 3×3 square CJK grid guard (90° CCW recheck), and clusters residual prose/narration bidirectionally (`h/w >= 1.5` vertical RTL `-cx, cy`; horizontal LTR `ymin, xmin`).
   - Clean CJK whitespace across both Japanese and Chinese (`clean_cjk_text`), and pass Unicode-detected `detected_source_lang` down to translators (`GoogleFreeTranslator` / `LLMTextTranslator`).
4. **100% Auto Extension UX & Backward-Compatible API Schema:**
   - Remove `#reader-mode-toggle` and `#source-lang-container` from Extension Popup (`popup.html`, `popup.ts`, `engine_selector_ui.ts`) and remove `sourceLang`/`reader_mode` forwarding from Extension IPC/storage/prefetch/gateway (preserving site reader DOM layout attributes `data-reader-mode` / `reader-mode`).
   - Keep `source_lang` and `reader_mode` optional with defaults (`"auto"`, `"manga"`) in backend `TranslationRequest` Pydantic schema for external API backward compatibility.

---

## 4. Consequences

- **Positive Impact:**
  - Seamless mixed-layout pages (curved speech bubbles + prose/narration blocks + horizontal/vertical text + mixed JA/ZH/EN) handled automatically in one pass without user toggling.
  - Sub-second GPU inference on AMD Radeon 780M (~330ms model compute total vs ~2500ms budget) within <2048 MB memory budget.
  - Cleaner popup UI free of redundant manual language/mode switches.
- **Trade-offs / Negatives:**
  - Slightly larger model disk footprint (~139 MB for `PP-OCRv6_medium` det+rec vs ~25 MB for legacy v3/v4, +13.5 MB when Korean is needed).
  - First Korean chapter page incurs one extra fast crop recognition pass (~40–85ms reusing existing crops) before chapter caching locks onto Korean.
- **Follow-up Tasks:**
  - Complete Phase 46 Tasks `46.1`–`46.10` in [tasks/todo.md](../../tasks/todo.md) and update [SPEC-local-engine.md](../specs/SPEC-local-engine.md) and [SPEC-popup-and-mascot-hud.md](../specs/SPEC-popup-and-mascot-hud.md).
