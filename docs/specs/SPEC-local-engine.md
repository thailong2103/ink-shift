# Spec: On-Device Manga Translation Engine (`local-engine`)

> **Module ID:** `local-engine`  
> **Source ADR:** [ADR-006-local-engine-architecture.md](../decisions/ADR-006-local-engine-architecture.md), [ADR-007-yolo11-manga-detection-and-visual-grounding.md](../decisions/ADR-007-yolo11-manga-detection-and-visual-grounding.md), [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md)  
> **Source Intent:** [docs/intent/local-engine.md](../intent/local-engine.md)  
> **Source Research:** [docs/research/RESEARCH-local-engine.md](../research/RESEARCH-local-engine.md) & [docs/research/RESEARCH-manga-detector-yolo11.md](../research/RESEARCH-manga-detector-yolo11.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Contract Spec:** [SPEC-api-contract.md](SPEC-api-contract.md)  
> **Backend Spec:** [SPEC-backend-engine.md](SPEC-backend-engine.md)  
> **Status:** Approved by Solo Developer (@human)  
> **Phase:** Module 5 Execution Runtime & Phase 15 Engine Restructure  
> **Quality Gate:** [CONSTRAINTS.md](../../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)  
> **Language Policy:** Official English document tracked in Git. Parallel Vietnamese copy at [docs/vi/specs/SPEC-local-engine.md](../vi/specs/SPEC-local-engine.md).  

---

## 1. Assumptions Surface

Before proceeding to implementation, the following architectural assumptions are recorded:
1. **Target Hardware & Acceleration:** Target workstation runs Windows 11 with an AMD Ryzen 7 8845HS APU (Zen 4, 8C/16T, AVX-512) and AMD Radeon 780M iGPU (RDNA 3, 12 CUs) backed by 32GB RAM (UMA). Microsoft DirectML via `onnxruntime-directml` serves as the primary hardware acceleration provider, with `CPUExecutionProvider` (AVX-512) as the automated node fallback.
2. **Permanent In-Memory Session Cache:** Given 32GB unified RAM and lightweight model weights (~39.3MB for YOLO11s-seg + ~15MB for RapidOCR), all ONNX `InferenceSession` instances (`YOLO11s-seg`, `RapidOCR`) remain resident in memory across requests. No unloading, disk re-reading, or memory deallocation occurs between page translations.
3. **Model Weight Storage:** Pre-trained ONNX model files are stored locally under `.cache/inkshift/models/yolo11s-seg.onnx`. Comic-Text-Detector weights are deprecated and purged.
4. **Coordinate Integrity:** Coordinate outputs strictly comply with `api-contract`: normalized integer bounding boxes $[ymin, xmin, ymax, xmax]$ in $[0, 1000]$, and simplified polygon contours as relative percentages $[0.0, 100.0]$.
5. **Zero API Cost by Default:** Default translation runs through `deep-translator` using Google Translate web batch requests, requiring $0.00$ API spend. An optional `LLMTextTranslator` mode reuses `gemini_api_key` and `xkiro_api_key` from Module 3 for enhanced literary phrasing.

---

## 2. Objective & Core Capabilities

Implement **Module 5 (`local-engine`)** as an on-device translation engine adhering to `BaseTranslationEngine`. Given an input manga page image (Base64 string or binary bytes), the engine detects speech bubbles and text layout via YOLO11s-seg, decodes smooth polygon masks, orders dialogue via 2-tier RTL manga reading order, extracts text via OCR, and translates dialogue into Vietnamese.

```mermaid
flowchart TD
    A["Raw Manga Image<br/>(Base64)"] --> DET["Stage 1: YOLO11s-seg Detector<br/>(DirectML FP16 / 1024x1024)"]
    DET --> POST["Stage 1.1: Mask Decoding & RDP Compression<br/>(18-25 Relative % Vertices, SFX Filtered)"]
    POST --> SORT["Stage 1.2: 2-Tier RTL Reading Order Sorter<br/>(Panel Top-Right-First + Score = 1.5Y - X)"]
    
    SORT --> ROU["Stage 2: RapidOCR DirectML Engine<br/>(Single-Pass Full-Page / Crop Multilingual & Japanese CJK)"]
    ROU --> MERGE["Extracted Text List"]
    
    MERGE --> TR{"Stage 3: Translator Router"}
    TR -->|Default ($0 Zero-Cost)| G_TR["GoogleFreeTranslator<br/>(deep-translator Batch Client)"]
    TR -->|Optional Pro (Text-Only Token)| LLM_TR["LLMTextTranslator<br/>(Gemini / OpenAI Text Client)"]
    
    G_TR --> OUT["TranslationResponse<br/>(TranslatedBlock list with [0, 1000] Box & Relative % Polygon)"]
    LLM_TR --> OUT
```

### Core Capabilities:
1. **YOLO11s-seg Instance Segmentation:** Detect `bubble`, `text`, and `panel` layout with DirectML hardware acceleration. Filter out `sfx` class. Extract 32 prototype masks and decode non-rectangular contours preserving character pointer tails.
2. **RDP Polygon Compression:** Apply Ramer-Douglas-Peucker (`cv2.approxPolyDP` with $eps=0.004$) to compress contours down to 18–25 vertices normalized as local relative percentages (`0%–100%`).
3. **2-Tier Deterministic Reading Order Sorter:**
   - **Tier 1 (Panel):** Assign bubbles to panels; sort panels Top-to-Bottom, Right-to-Left. Unassigned bubbles map to a default page panel.
   - **Tier 2 (In-Panel):** Sort bubbles inside each panel by $Score = 1.5Y - X$ (prioritizing top and right bubbles).
4. **Connected / Merged Bubble Support:** When adjacent speech bubbles merge into a single contour, YOLO11 separates independent child text blocks (`DetectedText`). Frontend renders 1 white polygon mask with multiple discrete inner text containers.
5. **Unified DirectML RapidOCR (ADR-017):** Single robust OCR engine wrapping PP-OCRv4 via ONNX Runtime DirectML. Natively supports Japanese (Kanji/Kana), English, Korean, and Chinese with sub-second execution on AMD Radeon 780M without requiring PyTorch or CUDA.
6. **Manga Typography & De-hyphenation:** Merge multi-line vertical Japanese text cleanly, and de-hyphenate multi-line English dialogue (`under-` + `stand` $\to$ `understand`).
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
rapidocr-onnxruntime = ">=1.3.0"
# manga-ocr ONNX graph or manga-ocr-torchless

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
├── detection/                 # Shared YOLO11 bubble segmentation & layout sorting
│   ├── __init__.py
│   ├── base.py                # BaseBubbleDetector protocol, DetectedBubble, DetectedText dataclasses
│   ├── yolo11_detector.py     # YOLO11s-seg ONNX DirectML detector (Option G1 Gateway Detector)
│   ├── postprocess.py         # 32 Proto-mask decoding, RDP compression (18-25 vertices), and box normalization
│   └── sorter.py              # 2-Tier RTL Manga Reading Order Sorter (Panel -> In-Panel 1.5Y - X)
└── engines/local/
    ├── __init__.py            # Exports LocalTranslationEngine, TranslatorRegistry
    ├── engine.py              # LocalTranslationEngine composite implementing BaseTranslationEngine
    ├── config.py              # Local engine configuration (paths, execution providers, timeouts)
    ├── ocr/
    │   ├── __init__.py
    │   ├── base.py            # BaseOCREngine protocol
    │   ├── rapid_ocr.py       # Multilingual & Japanese RapidOCR DirectML adapter
    │   ├── router.py          # OCRRouter (manual override + chapter cache)
    │   └── text_assembler.py  # De-hyphenator and comic line merger
    └── translator/
        ├── __init__.py
        ├── base.py            # BaseTextTranslator protocol
        ├── registry.py        # Dynamic TranslatorRegistry (google-free, llm-text)
        ├── google_free.py     # deep-translator GoogleTranslator batch client
        └── llm_text.py        # Text-only LLM translation client (reusing OpenAI-compatible endpoints)
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

    async def translate(self, request: TranslationRequest) -> TranslationResponse: ...
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

### 6.2 Dual OCR Execution Strategy: Single-Pass vs Crop Batching
To eliminate latency bottlenecks while preserving Japanese translation quality, `OCRRouter.recognize_routed_full_page` employs a dual-path execution strategy:

1. **Path A: Single-Pass Full-Page RapidOCR (Non-Japanese / Multilingual):**
   - Active for explicit non-JA models (`en`, `zh`, `ko`, `rapidocr`) or auto-detected non-JA chapters.
   - Bypasses dialogue cropping entirely. RapidOCR runs a single forward pass across the uncropped page ($W \times H$) with `use_cls=False`.
   - Detected text bounding polygons are matched to enclosing YOLO speech bubbles in canonical $[0, 1000]$ coordinates via spatial containment.
   - Text lines inside the same bubble are sorted vertically top-to-bottom and formatted via `assemble_comic_lines`.
   - Achieves a **7.16x – 10.6x speedup** (~430ms–1.2s on 2K/4K pages).

2. **Path B: Zero-Copy Memory Crop Batching (Japanese / MangaOCR):**
   - Active for explicit Japanese models (`ja`, `manga-ocr`) or when Kana characters are detected during auto probing.
   - Dialogue regions are sliced directly from in-memory NumPy arrays without disk I/O:
     ```python
     crop = original_ndarray[int(y_min) : int(y_max), int(x_min) : int(x_max)]
     ```
   - Slices are batched and passed to MangaOCR ONNX for high-accuracy vertical Japanese dialogue transcription.

### 6.3 Child Text Box Expansion in Polygon via Ray-Casting (`expand_child_text_boxes_in_polygon`)
To maximize translated text readability without crossing speech bubble contours:
1. **Ray-Casting Inside Mask:** From the initial bounding box of each text line/cluster, candidate boxes expand iteratively in 4 directions (top, bottom, left, right) inside the speech bubble's binary polygon mask.
2. **Mutual Exclusion:** When a bubble contains multiple child texts (`len(texts) > 1`), expanding boxes yield to avoid overlapping neighboring child boxes within the same parent bubble.
3. **Inscribed Safe-Zone for Starburst / Spiky Bubbles:** For non-rectangular speech bubbles (e.g. scream bubbles with spiky starburst contours), expansion stops at the innermost contour valleys ($55-60\%$ core width). The resulting `render_box` is inscribed inside the outer bounding box (`parent_box`), preventing long translated text lines from crossing spike valleys into adjacent artwork.
4. **Coordinate Mapping:** `render_box` is passed in `TranslatedBlock.box`, while `parent_box` holds the outer contour box, allowing the frontend renderer to anchor overlay text strictly inside the safe core.

### 6.4 Pseudo-Bubble Synthesis & Class-Specific Detection Thresholds
1. **Pseudo-Bubble Synthesis:** Dialogue text clusters (Class 3) whose center falls outside all detected speech bubbles (Class 0) are automatically wrapped into rectangular `DetectedBubble` records with 4% padding. This guarantees full capture of floating narrative thought monologues and rectangular narration boxes, while Class 2 (SFX sound effects) is intentionally ignored.
2. **Class-Specific Detection Thresholds:**
   - `bubble_threshold = 0.30`: High precision on speech bubble contours, eliminating false detections on circular background art.
   - `text_threshold = 0.30`: High recall on small or dense dialogue clusters.
   - `panel_threshold = 0.35`: Layout segmentation for Manga reading order sorting.

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

---

## 8. Memory Management & DirectML Session Lifecycle

1. **Warm Cache Policy:** All ONNX inference sessions (`YOLO11s-seg`, `RapidOCR`) are instantiated during the FastAPI server lifespan startup (`lifespan` in `app.py`).
2. **Provider Configuration:**
   ```python
   dml_providers = [
       (
           "DmlExecutionProvider",
           {
               "device_id": 0,
           },
       ),
       "CPUExecutionProvider",
   ]
   ```
3. **Session Re-use:** Sessions remain resident in memory for the life of the server process. Memory overhead ($\approx 250 - 300$ MB) accounts for $<1\%$ of the 32GB system memory.

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
- [ ] **SC-1 (Detector Accuracy):** `ComicTextDetector` detects speech bubbles in sample manga fixture images, returning $[ymin, xmin, ymax, xmax]$ boxes strictly bounded in $[0, 1000]$.
- [ ] **SC-2 (Japanese & Multilingual OCR):** `RapidOCRAdapter` accurately transcribes Japanese (Kanji/Kana) and Latin text from page crops or full-page input via DirectML.
- [ ] **SC-3 (Multilingual OCR & De-hyphenation):** `RapidOCRAdapter` extracts Latin text; `assemble_comic_lines` joins wrapped lines with spaces and removes line-ending hyphens.
- [x] **SC-4 (Language Routing & Override):**
  - When `source_lang="ja"` or `source_lang="en" | "ko" | "zh"` or `ocr_model="auto"`, routes cleanly to `RapidOCRAdapter` with zero probe failure.
  - Extension `source_lang="ja"` translates reliably without `RuntimeError` or `ENGINE_EXECUTION_FAILED`.
- [ ] **SC-5 (Zero-Cost Translation):** `GoogleFreeTranslator` translates a batch of 10 sentences to Vietnamese in $<400$ms.
- [ ] **SC-6 (End-to-End Latency):** Full page pipeline executes in $\le 2.5$ seconds on AMD Radeon 780M / 8845HS.
- [ ] **SC-7 (Quality Gate & Constraints):** Zero suppressions (`@ts-ignore`, `# noqa`, `# type: ignore`), strict mypy passes, test coverage across all new lines $\ge 80\%$.
- [ ] **SC-8 (Extension Compatibility):** Output `TranslationResponse` renders overlays cleanly inside the Chromium extension without frontend changes.
