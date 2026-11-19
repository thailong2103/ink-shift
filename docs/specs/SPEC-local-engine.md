# Spec: On-Device Manga Translation Engine (`local-engine`)

> **Module ID:** `local-engine`  
> **Source ADR:** [ADR-006-local-engine-architecture.md](../decisions/ADR-006-local-engine-architecture.md), [ADR-007-yolo11-manga-detection-and-visual-grounding.md](../decisions/ADR-007-yolo11-manga-detection-and-visual-grounding.md), [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md), [ADR-017-ocr-consolidation-and-directml-rapidocr.md](../decisions/ADR-017-ocr-consolidation-and-directml-rapidocr.md), [ADR-019-ppocrv6-unified-hybrid-detection-and-auto-ocr.md](../decisions/ADR-019-ppocrv6-unified-hybrid-detection-and-auto-ocr.md), [ADR-020-resilient-cache-site-adapters-priority-queue-and-llm-repair.md](../decisions/ADR-020-resilient-cache-site-adapters-priority-queue-and-llm-repair.md), [ADR-021-hybrid-directml-cpu-split-idle-unload-and-script-dominance.md](../decisions/ADR-021-hybrid-directml-cpu-split-idle-unload-and-script-dominance.md)  
> **Source Intent:** [docs/intent/local-engine.md](../intent/local-engine.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Contract Spec:** [SPEC-api-contract.md](SPEC-api-contract.md)  
> **Backend Spec:** [SPEC-backend-engine.md](SPEC-backend-engine.md)  
> **Status:** Implemented (Synced through Phase 48) — Approved by Solo Developer (@human)  
> **Phase:** Module 5 Execution Runtime & Phases 15–48 Hardening  
> **Quality Gate:** [CONSTRAINTS.md](../../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)  
> **Language Policy:** Official English document tracked in Git.

---

## 1. Assumptions Surface

Before proceeding to implementation, the following architectural assumptions are recorded:
1. **Target Hardware & Hybrid Acceleration (ADR-021):** Target workstation runs Windows 11 with an AMD Ryzen 7 8845HS APU (Zen 4, 8C/16T, AVX-512) and AMD Radeon 780M iGPU (RDNA 3, 12 CUs) backed by 32GB RAM (UMA). The default `hybrid` execution provider runs `YOLO11s-seg` and `PP-OCRv6_rec_medium` (+ lazy Korean `PP-OCRv5`) on Microsoft DirectML (`DmlExecutionProvider`, `enable_mem_pattern=False`, `ORT_SEQUENTIAL`) while executing `PP-OCRv6_det_medium` (DBNet) on `CPUExecutionProvider` (bounded `INKSHIFT_LOCAL_CPU_THREADS`), capping active GPU VRAM at ~608 MB. Both pure `directml` and pure `cpu` presets remain configurable via `.env`.
2. **Bounded Session Lifecycle with Idle Auto-Unload (180s TTL):** Given ~39.3MB (`YOLO11s-seg`) + ~139MB (`PP-OCRv6_medium`) + ~13.5MB (`korean_PP-OCRv5_rec_mobile`) ONNX weights, sessions initialize lazily on first inference and remain cached across page flips during active reading. When idle past `INKSHIFT_LOCAL_IDLE_UNLOAD_SECONDS` (default `180s`; `0` disables), a `PriorityLocalLock`-gated FastAPI background task automatically releases ONNX `InferenceSession` instances and triggers `gc.collect()`, dropping GPU VRAM from ~608 MB down to ~14.4 MB so concurrent local LLM runtimes (e.g., LM Studio) can claim VRAM freely.
3. **Model Weight Storage:** Pre-trained ONNX model files are stored locally under `.cache/inkshift/models/` (`yolo11s-seg.onnx`, `PP-OCRv6_det_medium.onnx`, `PP-OCRv6_rec_medium.onnx`, and lazy `korean_PP-OCRv5_rec_mobile.onnx`). Comic-Text-Detector weights are deprecated and purged.
4. **Coordinate Integrity:** Coordinate outputs strictly comply with `api-contract`: normalized integer bounding boxes $[ymin, xmin, ymax, xmax]$ in $[0, 1000]$, and simplified polygon contours as relative percentages $[0.0, 100.0]$.
5. **Zero API Cost by Default:** Default translation runs through `deep-translator` using Google Translate web batch requests, requiring $0.00$ API spend. An optional `LLMTextTranslator` mode reuses `gemini_api_key` and `xkiro_api_key` from Module 3 for enhanced literary phrasing.

---

## 2. Objective & Core Capabilities

Implement **Module 5 (`local-engine`)** as an on-device translation engine adhering to `BaseTranslationEngine`. Given an input manga page image (Base64 string or binary bytes), the engine detects speech bubbles and text layout via YOLO11s-seg, decodes smooth polygon masks, orders dialogue via 2-tier RTL manga reading order, extracts text via OCR, and translates dialogue into Vietnamese.

```mermaid
flowchart TD
    A["Raw Manga Image<br/>(Base64)"] --> DET["Stage 1: YOLO11s-seg detect_full_layout<br/>(Bubbles, Panels, SFX Mask, Orphan Texts)"]
    DET --> POST["Stage 1.1: Mask Decoding & RDP Compression<br/>(Chaikin B-Spline Contours, 18-25 Relative % Vertices)"]
    POST --> SORT["Stage 1.2: 2-Tier RTL Reading Order Sorter<br/>(Panel Top-Right-First + Score = 1.5Y - X)"]

    SORT --> ROU["Stage 2: OCRRouter.recognize_hybrid_page<br/>(Hybrid: DET CPU + REC DirectML + Lazy Korean Fallback)"]
    ROU --> FUSE["Spatial Fusion + Guards<br/>(IoMin SFX Exclusion, Panel/Bubble Barriers, 2D Union-Find)"]
    FUSE --> MERGE["Ordered Source Text Blocks<br/>(Bubbles + Residual Narration Clusters)"]

    MERGE --> TR{"Stage 3: TranslatorRegistry"}
    TR -->|Default ($0 Zero-Cost)| G_TR["GoogleFreeTranslator<br/>(deep-translator Batch + is_fallback Flag)"]
    TR -->|Optional LLM Text| LLM_TR["LLMTextTranslator<br/>(JSON Repair + _align_mismatched_translations)"]

    G_TR --> OUT["TranslationResponse<br/>(TranslatedBlock list + is_fallback Flag)"]
    LLM_TR --> OUT
```

### Core Capabilities:
1. **YOLO11s-seg Instance Segmentation:** Detect `bubble`, `text`, and `panel` layout with DirectML hardware acceleration. Filter out `sfx` class. Extract 32 prototype masks and decode non-rectangular contours preserving character pointer tails.
2. **RDP Polygon Compression:** Apply Ramer-Douglas-Peucker (`cv2.approxPolyDP` with $eps=0.004$) to compress contours down to 18–25 vertices normalized as local relative percentages (`0%–100%`).
3. **2-Tier Deterministic Reading Order Sorter:**
   - **Tier 1 (Panel):** Assign bubbles to panels; sort panels Top-to-Bottom, Right-to-Left. Unassigned bubbles map to a default page panel.
   - **Tier 2 (In-Panel):** Sort bubbles inside each panel by $Score = 1.5Y - X$ (prioritizing top and right bubbles).
4. **Connected / Merged Bubble Support:** When adjacent speech bubbles merge into a single contour, YOLO11 separates independent child text blocks (`DetectedText`). Frontend renders 1 white polygon mask with multiple discrete inner text containers.
5. **Unified Hybrid Detection & DirectML `PP-OCRv6_medium` (ADR-019):** Combines `YOLO11s-seg` (smooth curved bubble contours & SFX exclusion masks) with `PP-OCRv6_det_medium` + `PP-OCRv6_rec_medium` (`rapidocr>=3.9.1`, explicit DirectML `OrtInferSession` injection) in one pass—translating speech bubbles and residual non-SFX prose/narration clusters simultaneously across Japanese, Simplified/Traditional Chinese, and English, with automatic chapter-cached fallback to `korean_PP-OCRv5_rec_mobile` for Korean manhwa, bi-directional RTL/LTR clustering, Furigana filtering, and CJK de-spacing.
6. **Manga Typography & De-hyphenation:** Merge vertical RTL and horizontal LTR lines cleanly, strip CJK inter-character spaces across Japanese and Chinese (`clean_cjk_text`), and de-hyphenate multi-line English dialogue (`under-` + `stand` $\to$ `understand`).
7. **Fast Zero-Cost Batch Translation:** Translate all speech bubbles on a manga page in a single batch network call ($<350$ms) via `deep-translator`.

---

## 3. Tech Stack & Dependencies

### 3.1 Dependencies
```toml
# Hardware Acceleration & Inference
onnxruntime-directml = ">=1.17.0"
opencv-python-headless = ">=4.9.0"
numpy = ">=1.26.0"
Pillow = ">=10.2.0"

# OCR Engines
rapidocr = ">=3.9.1"

# Translation
deep-translator = ">=1.11.4"
httpx = ">=0.27.0"
```

### 3.2 Verification Commands
```bash
# Floor Guard + Types + Linting
python scripts/check.py --fast

# Full Task Gate (Diff-scoped coverage >= 80%)
python scripts/check.py --task

# Targeted Unit Tests for Local Engine
pytest tests/backend/engines/local/ -v --asyncio-mode=auto
```

---

## 4. Project Structure

```
src/backend/
├── config.py                  # Global environment settings (paths, execution provider, timeouts)
├── detection/                 # Shared YOLO11 bubble/layout segmentation & assembly
│   ├── __init__.py
│   ├── assembler.py           # BubbleWorkItem & polygon safe-zone ray-casting expansion
│   ├── base.py                # BaseBubbleDetector, DetectedBubble, DetectedPanel, DetectedText, PageLayoutDetections
│   ├── downloader.py          # Hugging Face (YOLO11) & ModelScope (PP-OCRv6 / Korean PP-OCRv5) downloader
│   ├── postprocess.py         # Prototype mask decoding, Chaikin smoothing, RDP compression, orphan partition
│   ├── sorter.py              # 2-Tier RTL Manga Reading Order Sorter (Panel -> In-Panel 1.5Y - X)
│   └── yolo11_detector.py     # YOLO11s-seg ONNX DirectML detector (detect & detect_full_layout)
└── engines/local/
    ├── __init__.py            # Exports LocalTranslationEngine, OCRRouter, RapidOCRAdapter, TranslatorRegistry
    ├── engine.py              # LocalTranslationEngine composite forwarding panels/orphans & unified ordering
    ├── ocr/
    │   ├── __init__.py
    │   ├── base.py            # BaseOCREngine / FullPageOCREngine protocols
    │   ├── rapid_ocr.py       # PP-OCRv6_medium & lazy Korean PP-OCRv5 adapter (explicit DirectML ORT injection)
    │   ├── router.py          # OCRRouter (recognize_hybrid_page, IoMin SFX filter, noise guard, chapter cache)
    │   └── text_assembler.py  # 2D Union-Find clustering, panel/bubble barriers, Furigana & 3x3 CJK guards, clean_cjk_text
    └── translator/
        ├── __init__.py
        ├── base.py            # BaseTextTranslator protocol & TranslationBatch(is_fallback)
        ├── registry.py        # Dynamic TranslatorRegistry (google-free, llm-google, llm-openai, llm-anthropic, llm-custom)
        ├── google_free.py     # deep-translator GoogleTranslator + MyMemory fallback batch client
        └── llm_text.py        # Text-only LLM client (<think> strip, JSON repair, retry, count alignment)
```

---

## 5. Public Interfaces & Component Contracts

### 5.1 Detector Protocol (`detector/base.py`)
```python
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DetectedText:
    """Represents a localized line or paragraph of text inside a bubble."""

    box_2d: tuple[int, int, int, int]  # (ymin, xmin, ymax, xmax) in [0, 1000]
    confidence: float = 1.0


@dataclass(frozen=True)
class DetectedBubble:
    """Represents a localized speech bubble with curved contour and child texts."""

    id: str
    box_2d: tuple[int, int, int, int]  # (ymin, xmin, ymax, xmax) in [0, 1000]
    polygon: list[tuple[float, float]] = field(default_factory=list)  # 18-25 [x, y] in 0.0-100.0%
    texts: list[DetectedText] = field(default_factory=list)  # Child text boxes
    panel_index: int = -1  # Panel group ID for reading order
    confidence: float = 1.0


@runtime_checkable
class BaseBubbleDetector(Protocol):
    """Contract for text bubble detection backends (YOLO11s-seg)."""

    @property
    def name(self) -> str: ...

    async def is_available(self) -> bool: ...

    async def detect(
        self, image_bytes: bytes, original_width: int, original_height: int
    ) -> list[DetectedBubble]:
        """Detect speech bubbles and return ordered bubbles with [0, 1000] boxes and polygons."""
        ...
```

### 5.2 OCR Protocols (`ocr/base.py`)
```python
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable
import numpy as np
from PIL import Image
from src.backend.detection.assembler import BubbleWorkItem


class BaseOCREngine(Protocol):
    """Contract for speech bubble text recognition."""

    @property
    def name(self) -> str: ...

    async def is_available(self) -> bool: ...

    async def recognize_batch(self, image_crops: list[bytes]) -> list[str]:
        """Extract text strings from cropped speech bubble images."""
        ...


@runtime_checkable
class FullPageOCREngine(Protocol):
    """Protocol for OCR engines supporting uncropped single-pass page recognition."""

    @property
    def name(self) -> str: ...

    @property
    def supports_full_page(self) -> bool: ...

    async def is_available(self) -> bool: ...

    async def recognize_full_page(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
    ) -> list[str]:
        """Recognize text across entire page and map into speech bubbles via spatial containment."""
        ...
```

### 5.3 Translator Protocol (`translator/base.py`)
```python
from typing import Protocol


class BaseTextTranslator(Protocol):
    """Contract for text translation backends."""

    @property
    def name(self) -> str: ...

    async def translate_batch(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[str]:
        """Translate a list of dialogue strings to the target language."""
        ...
```

### 5.4 Composite Engine (`engine.py`)
```python
class LocalTranslationEngine(BaseTranslationEngine):
    """Composite local manga translation engine running on DirectML."""

    def __init__(
        self,
        detector: BaseBubbleDetector,
        ocr_router: OCRRouter,
        translator: BaseTextTranslator,
        name: str = "local",
    ) -> None:
        self._name = name
        self._detector = detector
        self._ocr_router = ocr_router
        self._translator = translator

    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
        layout: PageLayoutDetections | None = None,
    ) -> TranslationResponse: ...
```

---

## 6. Pipeline Workflow & Coordinate Normalization

### 6.1 Coordinate Transformation Math
1. `YOLO11s-seg` operates on square letterboxed input (e.g. $1024 \times 1024$).
2. Output polygon vertices $(x_m, y_m)$ are rescaled back to original image dimensions $(W, H)$:
   $$x_{orig} = \frac{x_m - pad_x}{scale}, \quad y_{orig} = \frac{y_m - pad_y}{scale}$$
3. An axis-aligned bounding box $[x_{min}, y_{min}, x_{max}, y_{max}]$ is calculated from the polygon vertices.
4. Bounding box coordinates are normalized into integer $[0, 1000]$ coordinates:
   $$ymin = \text{round}\left(\frac{y_{min}}{H} \times 1000\right), \quad xmin = \text{round}\left(\frac{x_{min}}{W} \times 1000\right)$$
   $$ymax = \text{round}\left(\frac{y_{max}}{H} \times 1000\right), \quad xmax = \text{round}\left(\frac{x_{max}}{W} \times 1000\right)$$
5. Bounded clamping guarantees: $0 \le ymin < ymax \le 1000$ and $0 \le xmin < xmax \le 1000$.

### 6.2 Unified Hybrid Auto-OCR Execution Strategy (`OCRRouter.recognize_hybrid_page`)
Per ADR-019 and Phase 47, `OCRRouter.recognize_hybrid_page()` eliminates legacy manual mode/language branching (`MangaOCR` Path B is removed) in favor of a single-pass unified pipeline:

1. **Single-Pass Split Detection (`PP-OCRv6_det_medium`):** Runs DBNet once on the full BGR page (`limit_side_len=1280` configurable via `INKSHIFT_LOCAL_OCR_DET_LIMIT_SIDE_LEN`, `thresh=0.2`, `box_thresh=0.35`, `unclip_ratio=1.8`) on `CPUExecutionProvider` under default `hybrid` mode, returning oriented text quads while eliminating high-resolution tick noise and DirectML workspace spikes.
2. **Spatial Partition & IoMin SFX Exclusion:**
   - **Bucket A (Curved Speech Bubbles):** Quads whose normalized centroid falls within `work_items[i].crop_box` (with 6‰ margin, choosing smallest enclosing bubble).
   - **Bucket B (Residual Non-Bubble Lines):** Quads outside all speech bubbles that do NOT overlap YOLO `sfx_boxes` via `_overlaps_any_box_iomin()` (`inter_area / min(q_area, sfx_area) >= 0.40`).
3. **Pre-Recognition Furigana Filter & One-Shot Crop Reuse:** Vertical ruby strips (`w < 0.55 * median_w` immediately right of vertical columns) are excluded before cropping (`crop_quad()`). All remaining crops run in 1 batched inference call on `PP-OCRv6_rec_medium` (`DmlExecutionProvider`, ~18,708 chars covering ZH/JA/EN). If bubble crops yield low confidence (`< 0.72` avg or `> 35%` empty without Kana), `OCRRouter` lazily invokes `korean_PP-OCRv5_rec_mobile` reusing the exact same cropped arrays and caches `"ko"` by `chapter_id`. Language identification (`detect_page_language()`) uses dominant-script ratios (`latin_count >= 8` and `latin_count >= 4 * cjk_total`) so stray false-positive CJK characters cannot hijack English pages.
4. **3×3 Ambiguous Square CJK Guard:** Square tight CJK speech bubbles on vertically dominant pages are rotated 90° CCW (`recheck_ambiguous_square_bubble`) if DBNet sliced vertical columns horizontally.
5. **Phase 47 2D Union-Find Residual Clustering & Noise Guard (`text_assembler.py`, `router.py`):**
   - `cluster_lines_bidirectional()` partitions residual lines using **distance-ordered 2D Union-Find** (`_union_find_cluster_entries`, `<= 2.8x` font-scale parity) instead of greedy 1-pass scans, preventing cross-panel X-column or Y-row bridging.
   - `LocalTranslationEngine` forwards `panel_boxes` and `orphan_boxes` from `PageLayoutDetections`: inset-aware `_assign_panel_index()` isolates panels, while `_overlaps_any_bubble()` rejects merges covering `>25%` of a speech bubble and drops residual clusters covering `>30%`.
   - Context-aware residual filters (`min_conf = 0.50` for `orphan_boxes`, `0.55` default on bubble pages, `0.40` on pure prose pages, plus `_is_residual_noise_cluster`) eliminate background handwritten noise, stray digits, and short uppercase ASCII artifacts.

### 6.3 Child Text Box Expansion in Polygon via Ray-Casting (`expand_child_text_boxes_in_polygon`)
To maximize translated text readability without crossing speech bubble contours:
1. **Ray-Casting Inside Mask:** From the initial bounding box of each text line/cluster, candidate boxes expand iteratively in 4 directions (top, bottom, left, right) inside the speech bubble's binary polygon mask.
2. **Mutual Exclusion:** When a bubble contains multiple child texts (`len(texts) > 1`), expanding boxes yield to avoid overlapping neighboring child boxes within the same parent bubble.
3. **Inscribed Safe-Zone for Starburst / Spiky Bubbles:** For non-rectangular speech bubbles (e.g. scream bubbles with spiky starburst contours), expansion stops at the innermost contour valleys ($55-60\%$ core width). The resulting `render_box` is inscribed inside the outer bounding box (`parent_box`), preventing long translated text lines from crossing spike valleys into adjacent artwork.
4. **Coordinate Mapping:** `render_box` is passed in `TranslatedBlock.box`, while `parent_box` holds the outer contour box, allowing the frontend renderer to anchor overlay text strictly inside the safe core.

### 6.4 Layout Partition (`PageLayoutDetections`) & Class-Specific Detection Thresholds
1. **Non-Fragmented Layout Output (ADR-019):** `YOLO11Detector.detect_full_layout()` sets `synthesize_orphan_bubbles=False` so orphan texts (Class 3) outside speech bubbles are kept in `PageLayoutDetections.orphan_texts` rather than fragmented into rectangle pseudo-bubbles. Both ordered curved bubbles (`blocks` with `polygon`) and residual prose clusters (`id="text_p_*"`, `polygon=None`) are merged into unified reading order (`_reading_order_key`) and translated together in one batch.
2. **Class-Specific Detection Thresholds:**
   - `bubble_threshold = 0.30`: High precision on speech bubble contours, eliminating false detections on circular background art.
   - `text_threshold = 0.30`: High recall on small or dense dialogue clusters inside bubbles.
   - `panel_threshold = 0.35` & `sfx_threshold = 0.35`: Panel barrier segmentation and NMS-filtered SFX exclusion masks.

---

## 7. Multi-line Text Assembly & De-hyphenation Algorithm

For Latin-script text extracted via `RapidOCR`:
```python
import re


def assemble_comic_lines(raw_lines: list[str]) -> str:
    """Merge segmented lines inside a speech bubble and remove hyphenation."""
    merged = ""
    for line in raw_lines:
        cleaned = line.strip()
        if not cleaned:
            continue

        if merged.endswith("-"):
            # Check if this is a split word (e.g. "dis-" + "appear" -> "disappear")
            # If the next line starts with lowercase or continuation, strip hyphen
            if re.match(r"^[a-z]", cleaned):
                merged = merged[:-1] + cleaned
            else:
                merged = merged + " " + cleaned
        else:
            merged = (merged + " " + cleaned).strip()

    return merged
```

### 7.2 Resilient Local LLM JSON Repair & Fallback Tagging (`llm_text.py`, Phase 45)
- `LLMTextTranslator` strips `<think>...</think>` reasoning blocks (`_clean_raw_response`), repairs trailing commas, single-quoted Python literals, or unescaped inner quotes (`_repair_malformed_json_array`), logs failures (`LLMParseFailed`), retries once with strict item count enforcement, and recovers minor length mismatches via `_align_mismatched_translations()`.
- When upstream translation fails or preserves untranslated text, both `GoogleFreeTranslator` and `LLMTextTranslator` return `TranslationBatch(..., is_fallback=True)` so `POST /api/v1/translate` skips SQLite caching cleanly.

---

## 8. Memory Management & Hybrid DirectML/CPU Session Lifecycle

1. **Lazy Session Initialization:** `YOLO11Detector._ensure_session()`, `RapidOCRAdapter._ensure_det_and_rec()`, and `_ensure_ko_rec()` load ONNX Runtime sessions lazily on first inference request (not at FastAPI startup, where baseline Python consumes ~61 MB WS and 0 MB GPU VRAM). `RapidOCRAdapter._create_ort_session()` and `YOLO11Detector._ensure_session()` bypass the `rapidocr==3.9.1` OmegaConf `DictConfig` bug and share uniform sequential `SessionOptions`.
2. **Hybrid Provider & SessionOptions Configuration (ADR-021):**
   - `INKSHIFT_LOCAL_EXECUTION_PROVIDER=hybrid` *(default)*:
     - `YOLO11s-seg` & `PP-OCRv6_rec_medium` (+ lazy `korean_PP-OCRv5_rec_mobile`): `[("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"]` with `enable_mem_pattern = False` and `execution_mode = ORT_SEQUENTIAL` (preserving DirectML arena reuse so latency stays optimal).
     - `PP-OCRv6_det_medium` (DBNet): `["CPUExecutionProvider"]` with `intra_op_num_threads = INKSHIFT_LOCAL_CPU_THREADS` (default `min(8, max(1, os.cpu_count() or 4))`) and `limit_side_len = INKSHIFT_LOCAL_OCR_DET_LIMIT_SIDE_LEN` (default `1280`).
   - Alternate modes: `"directml"` (GPU for all 3 models; ~1.89–3.31 GB VRAM) and `"cpu"` (`0 MB` GPU VRAM; ~2.17s/page).
3. **Bounded Idle Auto-Unload & Measured Footprint (Verified Hardware Telemetry):**
   - On `1125×1600` pages under default `hybrid` + `limit_side_len=1280`, measured active footprint is **608.0 MB GPU VRAM** (36.8 MB dedicated + 571.2 MB shared, fixed regardless of source image resolution) and ~1.2–1.5s warm inference latency.
   - FastAPI `lifespan()` spawns `_idle_unload_loop` checking `maybe_unload_idle_local_models()` gated behind `PriorityLocalLock` (`P2` priority + double-checked timestamps). When idle for `INKSHIFT_LOCAL_IDLE_UNLOAD_SECONDS` (default `180.0s`, `0` disables), `unload_session()` and `unload_sessions()` drop GPU VRAM to **14.4 MB** (~22 MB inclusive of process overhead) and cut RAM Working Set roughly in half; subsequent requests transparently reload sessions with zero memory leak (verified reloading back to **608.0 MB** GPU VRAM).

---

## 9. Error Handling & Degradation Fallbacks

| Scenario | Local Engine Behavior | Status Code / Response |
|---|---|---|
| **No bubbles detected** | Returns empty `blocks=[]` with `execution_time_ms`. | 200 OK |
| **Model weights missing on disk** | Triggers automated download. If network down, raises `ModelFileNotFoundError`. | 500 APIErrorDetail |
| **DirectML device failure** | Automatically falls back to `CPUExecutionProvider` without failing. | 200 OK |
| **Google Translate Rate Limit (429)** | Exponential backoff retry ($\le 2$ retries). If exhausted, falls back to source text. | 200 OK (with source text) |
| **Uncorrelatable Unicode script** | Defaults to `RapidOCR` general recognition. | 200 OK |

---

## 10. Test Matrix & Acceptance Criteria

### 10.1 Success Criteria (SC)
- [x] **SC-1 (Detector Accuracy):** `YOLO11Detector` detects speech bubbles, panels, SFX masks, and orphan texts, returning $[ymin, xmin, ymax, xmax]$ boxes strictly bounded in $[0, 1000]$.
- [x] **SC-2 (Unified Multilingual & Auto-Korean OCR):** `RapidOCRAdapter` + `OCRRouter.recognize_hybrid_page()` accurately transcribes Japanese, Chinese, English (`PP-OCRv6_medium`), and lazy-fallback Korean (`korean_PP-OCRv5_rec_mobile`) on DirectML.
- [x] **SC-3 (Bi-Directional Clustering & Noise Guards):** `cluster_lines_bidirectional()` separates vertical RTL and horizontal LTR residual prose blocks via 2D Union-Find without cross-panel bridging, bubble overlap, or SFX leakage.
- [x] **SC-4 (Automatic Language Detection & Routing):** Routes cleanly in `auto` mode and detects source script (`ja`, `zh`, `ko`, `en`) without manual popup toggles.
- [x] **SC-5 (Zero-Cost & Resilient LLM Translation):** `GoogleFreeTranslator` and `LLMTextTranslator` translate batches cleanly and surface `is_fallback` flags on failure.
- [x] **SC-6 (End-to-End Inference Latency):** Local detection + hybrid OCR executes cleanly within $\le 2.5$ seconds per page on AMD Radeon 780M DirectML.
- [x] **SC-7 (Quality Gate & Constraints):** Zero suppressions (`@ts-ignore`, `# noqa`, `# type: ignore`), strict mypy passes, Ruff passes cleanly.
- [x] **SC-8 (Extension Compatibility):** Output `TranslationResponse` renders curved bubble polygons and flat residual prose blocks cleanly inside the Chromium extension.
