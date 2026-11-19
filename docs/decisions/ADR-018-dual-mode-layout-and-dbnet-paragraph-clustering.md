# ADR-018: Dual-Mode Layout Engine (Manga Comic Bubble vs. Web Prose/Novel Mode) with DBNet Paragraph Envelope Clustering

- **Status:** Superseded by ADR-019
- **Date:** 2026-11-02
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

InkShift was initially architected around manga comic translation: images are evaluated by YOLO11s-seg to detect speech balloon contours, sorted using Right-to-Left (RTL) manga reading order, and wrapped inside comic bubble overlays.

However, real-world testing against long-form text screenshots (such as Japanese novel pages, digital constitutions, or news articles) revealed three critical failure modes:
1. **YOLO11s-seg Over-Segmentation on Long-Form Prose:** YOLO11 splits contiguous paragraphs into dozens of micro-boxes (e.g. 18 fragmented slivers across 6 lines of text).
2. **Right-to-Left Reading Inversion:** Because manga order sorts top-to-bottom and right-to-left, horizontal Yokogaki lines are sorted in reverse, garbling the grammar of Japanese and Western sentences.
3. **RapidOCR Singleton Pool Aliasing:** When the default (Chinese/Latin PP-OCRv4) engine was warmed up, subsequent requests for Japanese OCR (`ja`) or Korean (`ko`) were inadvertently routed to the default instance unless a specialized engine was isolated.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A: Retrain YOLO11 for Prose Paragraphs** | Single pipeline for both manga and prose. | Requires gathering thousands of annotated novel pages, training time, high risk of regression on comic bubbles. | Not recommended. |
| **Option B: Dual-Mode Architecture with DBNet Line-Clustering Envelope (Selected)** | - Bypasses YOLO completely in text mode, eliminating 700ms+ inference latency.<br>- DBNet natively detects all text lines.<br>- Envelope clustering ($\Delta Y \le 1.2\bar{h}$) groups consecutive lines into cohesive paragraphs.<br>- Native LTR reading order.<br>- Zero regression on existing manga comic workflows. | Adds a layout toggle (`reader_mode: 'manga' \| 'text'`) to Extension and API contract. | **Recommended & Adopted.** |

---

## 3. Decision & Rationale

We adopted **Option B**:
1. **Contract Expansion:** Added `reader_mode: Literal["manga", "text"] = "manga"` to `TranslationRequest` and `TranslateImagePayload`.
2. **DBNet Envelope Clustering:** Created `cluster_lines_to_paragraphs()` in `src/backend/engines/local/ocr/text_assembler.py`. RapidOCR's DBNet lines are sorted vertically by $y_{min}$ and merged when vertical gap $\Delta Y \le 1.2\bar{h}$ and horizontal overlap $overlap_x > 0$. The resulting paragraph envelope takes $(ymin=\min, xmin=\min, ymax=\max, xmax=\max)$.
3. **Engine Pool Isolation:** Added `self._custom_engine_provided` guard to `RapidOCRAdapter._get_engine()` so default engine initialization never poisons language-specific neural model routing.
4. **Cache Key Partitioning:** In SQLite cache, `engine_used` is saved as `f"{engine}:{reader_mode}"` when `reader_mode != "manga"`, preventing manga and prose cache collisions for identical images.
5. **UI & Typography:** Added segmented toggle `[📖 Manga | 📄 Văn bản]` in Popup. Paragraph overlays omit comic SVG polygon clipping and render with `border-radius: 4px`, `text-align: left`, and clean system sans-serif typography (`system-ui, -apple-system, 'Segoe UI', Roboto, Noto Sans, sans-serif`).

---

## 4. Consequences
- **Positive Impact:**
  - Japanese text recognition achieved 99.12% character similarity on actual 170-character excerpt.
  - Prose translation latency dropped by 700ms+ due to skipping YOLO11 segmentation.
  - Zero regression across all 328 extension tests and 331 backend tests (100% green).
- **Trade-offs / Negatives:**
  - User explicitly selects between Manga and Text mode (or relies on default Manga mode).
- **Follow-up Tasks:**
  - Automated layout auto-detection heuristic based on text density and contour aspect ratio in future iterations.

