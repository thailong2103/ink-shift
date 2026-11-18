# ADR-007: Comprehensive Detection & Translation Pipeline Upgrade with YOLO11s-seg, Polygon Compression, and Set-of-Marks Visual Grounding

- **Status:** Accepted
- **Date:** 2026-10-16
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** AI Agent
- **Target Modules:** `local-engine`, `cloud-engine`, `extension-core`, `api-contract`
- **Amended By:** [ADR-008](ADR-008-consolidated-engine-architecture-and-shared-detection.md) (Detector extracted to root src/backend/detection/; Option G1 gateway-level pre-detection)
- **Supersedes:** [ADR-006](ADR-006-local-engine-architecture.md) (Section 2.B Text Bubble Detection Model)
- **Amends:** [ADR-004](ADR-004-cloud-engine-architecture.md) (Cloud Multimodal Prompting) and [ADR-005](ADR-005-extension-core-architecture.md) (Extension Overlay Rendering)
- **Relevant Skills:** `documentation-and-adrs`, `api-and-interface-design`, `performance-optimization`

---

## 1. Context & Problem Statement

Following the initial delivery of Module 5 (`local-engine`) and live browser extension testing, an empirical audit and benchmark on real-world manga panels ([RESEARCH-manga-detector-yolo11.md](../research/RESEARCH-manga-detector-yolo11.md)) revealed critical bottlenecks across both local and cloud pipelines:

1. **Severe Dropout in Comic-Text-Detector:** The baseline detector missed **60%–82%** of dialogue balloons across complex manga panels. Being a text-only detector, it lacked speech balloon awareness, balloon contour segmentation, and character pointer (tail) preservation.
2. **Artwork Occlusion from Rectangular Overlays:** Standard axis-aligned bounding boxes forced rectangular white overlays over curved speech balloons, occluding characters' faces, hair, and background screentones.
3. **Cloud Engine Latency and Token Inefficiency:** Requiring Cloud LLMs (Gemini 2.0 Flash) to predict spatial coordinates (`box_2d`) consumed ~1,000 output tokens, induced severe alignment drift/hallucinations, and required **12–15 seconds** per page.
4. **Connected / Merged Speech Balloons:** Manga characters frequently utter connected phrases where 2–3 balloons touch or merge into a single contour. Rectangular detectors merged these into a single monolithic block, breaking text layout.
5. **Manga Reading Order Ambiguity:** Without explicit reading order modeling, translated dialogue was frequently presented out of narrative sequence (reading left-to-right rather than traditional Japanese Right-to-Left, Top-to-Bottom).

To solve these foundational issues, we establish a comprehensive upgrade across detection, geometry compression, visual grounding, and frontend typography.

---

## 2. Options Considered & Architectural Decisions

### A. Speech Bubble & Layout Detector
| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Option 1A: YOLO11s-seg ONNX DirectML (Selected)** | - Dual-head architecture: Bounding Boxes + 32 Prototype Masks.<br>- 4 distinct classes: `bubble`, `text`, `panel`, `sfx`.<br>- Lightweight (39.3 MB) and fast (~80–100ms on AMD Radeon 780M via DirectML).<br>- Detects both macro-bubbles and micro-text blocks independently. | - Requires post-processing for polygon contour decoding. | **Selected (Agent & Human Approved)** |
| **Option 1B: Comic-Text-Detector (Previous Baseline)** | - Trained specifically on comic lines. | - Severe 60%–82% dropout rate; zero bubble mask awareness; box-only output. | **Superseded & Completely Removed** |
| **Option 1C: RT-DETR-v2 FP16** | - Transformer bipartite matching; NMS-free. | - Larger weight size (80.8 MB); bounding box output only (no polygon masks). | Rejected |

> **Clean Cut Rule:** Comic-Text-Detector and its model weights are completely excised from the repository. No backward-compatibility flags or `if/else` legacy branches are retained.

---

### B. Mask Data Compression & Transmission Format
| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Option 2A: RDP Polygon Compression (`cv2.approxPolyDP`) as Relative % (Selected)** | - Simplifies raw ~800-pixel contours down to **18–25 smooth vertices**.<br>- Total page JSON payload is only **~3–5 KB** (transfers over localhost in $<0.1$ms).<br>- Normalizing as Relative Percentage (`0%–100%` relative to bubble box) maps directly to CSS `clip-path: polygon(...)` with zero frontend recalculation. | - Requires OpenCV post-processing (~30ms CPU). | **Selected (Agent & Human Approved)** |
| **Option 2B: Transmitting 2D Binary Raster Masks** | - Pixel-perfect representation. | - Massive JSON payloads (8–12 MB per page); causes browser main-thread freezes and IPC bottlenecks. | Rejected |
| **Option 2C: Full-Page Global Coordinates `[0, 1000]`** | - Matches `box_2d` space. | - Forces frontend to recalculate relative percentages per container, adding arithmetic risk. | Rejected |

---

### C. Cloud Engine Architecture: Set-of-Marks (Visual Grounding)
| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Option 3A: Local YOLO11 Pre-detection + Set-of-Marks (SoM) + Gemini Translation (Selected)** | - Backend runs YOLO11 locally (~80ms), drawing thin 1px boundary outlines and sequential number badges `[1], [2]...` on bubbles.<br>- Gemini receives marked image and returns an ultra-compact flat JSON: `{"1": "Translation 1", "2": "Translation 2"}`.<br>- **Zero coordinate drift**; token usage drops by 90%; response time drops from 15s to **~1s**. | - Requires backend to have local YOLO11 active before calling Cloud LLM. | **Selected (Agent & Human Approved)** |
| **Option 3B: Pure Cloud Vision Prompting (Previous Baseline)** | - Single round-trip to Gemini. | - High token cost (~1,000 tokens); frequent coordinate hallucinations; 12–15s latency. | **Superseded** |

---

### D. Reading Order Sorting: 2-Tier Deterministic Geometric Sorter
| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Option 4A: 2-Tier Hierarchical Geometric Sorter (Selected)** | - **Tier 1 (Panel):** Groups bubbles into YOLO11-detected panels; sorts panels Top-to-Bottom, Right-to-Left (Japanese standard).<br>- **Tier 2 (In-Panel):** Sorts bubbles inside each panel by $Score = 1.5Y - X$ (prioritizing top and right).<br>- Fallback: Unassigned bubbles default to root page panel `[0, 0, 1000, 1000]`.<br>- Latency $<0.1$ms, 100% deterministic, zero AI model overhead. | - None for standard manga layouts. | **Selected (Agent & Human Approved)** |
| **Option 4B: AI Reading Order Classifier (GNN / LayoutLM)** | - Learns non-standard comic flows. | - Adds heavyweight model dependency ($>100$MB); increases inference latency. | Rejected |

---

### E. Frontend Typography & Overlay: Two-Layer Architecture
| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Option 5A: Two-Layer Pattern with Binary Search Auto Font-Fit (Selected)** | - **Layer 1 (Background Mask):** Dedicated `div` with `clip-path: polygon(...)` and white fill, hugging bubble contour and tail perfectly.<br>- **Layer 2 (Text Container):** Positioned inside Inner Safe-Zone (10%–15% inset) or child text box; **not clipped**, preventing character truncation.<br>- **Auto Font-Fit:** Binary search between 10px and 22px (line-height 1.25) ensures optimal readability without overflow. | - Slightly more DOM elements (2 elements per bubble). | **Selected (Agent & Human Approved)** |
| **Option 5B: Single Clipped Container** | - 1 DOM element per bubble. | - Any text reaching into the narrow balloon tail is clipped in half by CSS. | Rejected |

---

### F. SFX (Sound Effects) Policy
- **Decision:** Temporarily **ignore and filter out** the `sfx` class detected by YOLO11.
- **Rationale:** Sound effects in manga are hand-drawn artistic elements intertwined with background artwork. Overlaying them with solid masks destroys aesthetic immersion. InkShift focuses purely on character dialogue balloons.

---

## 3. Consequences

### Positive Consequences:
1. **Pristine Aesthetics:** Speech bubble overlays hug author artwork contours with 18–25 vertex polygons, leaving characters' hair, faces, and backgrounds 100% intact.
2. **Cloud Latency Revolution:** Gemini vision latency drops from 12–15s down to ~1.0s, with zero bounding box hallucinations.
3. **Bandwidth Efficiency:** JSON payload stays within 3–5 KB per page over localhost loopback.
4. **Dialogue Flow:** Strict 2-tier geometric sorting guarantees translations read in Japanese narrative order.
5. **Connected Bubbles Solved:** Multiple child text blocks within a single merged bubble contour are rendered into separate safe-zone containers.

### Negative Consequences & Required Migrations:
1. **Model Provisioning:** `scripts/download_models.py` must be updated to retrieve `yolo11s-seg.onnx` (39.3 MB) and deprecate `comic_text_detector.onnx`.
2. **API Contract Evolution:** `SPEC-api-contract.md`, `TranslatedBlock` in Pydantic and TypeScript must support the optional `polygon` relative array.
3. **Test Fixtures:** Unit tests in `tests/backend/engines/local/` must be updated to assert YOLO11 tensor processing and RDP polygon math.
