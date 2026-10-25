# Spec: API Contract and Data Exchange Protocol (`api-contract`)

> **Module ID:** `api-contract`  
> **Source ADR:** [ADR-002-api-contract-and-data-exchange.md](../decisions/ADR-002-api-contract-and-data-exchange.md), [ADR-007-yolo11-manga-detection-and-visual-grounding.md](../decisions/ADR-007-yolo11-manga-detection-and-visual-grounding.md), [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Status:** Approved by Solo Developer (@human)  
> **Phase:** Module 1 Foundation & Phase 15 Consolidation  

---

## 1. Objective

Define the immutable data contract, coordinate system, error models, and communication endpoints between the Chromium Browser Extension (`extension-core`) and the Local FastAPI Backend (`backend-engine`).

### Core Goals:
1. **Decouple Frontend & Backend:** Both sides can be built, verified, and mocked independently against a single shared contract schema.
2. **Provider Agnostic (Pluggable Engines):** Whether backend runs Cloud AI (Gemini / OpenAI) or Local Offline Pipeline (YOLO11 + OCR + Translation), the output contract delivered to the Extension remains 100% identical.
3. **Coordinate Precision:** Standardize all bounding boxes on normalized integer scale `[0, 1000]` for zero floating-point drift and instant browser scaling.
4. **Optimized Page-by-Page Reading:** Support high-speed cache checks (`GET /api/v1/cache/{image_hash}`) preventing redundant Base64 payload transfer.
5. **Robust Typography & Render Guidance:** Ensure schemas support Vietnamese typography without breaking words mid-string or clipping accents vertically.

---

## 2. Tech Stack & Environment

- **Schema Definition:** Pydantic v2 (Python) & TypeScript 5 interfaces.
- **Contract Validation:** JSON Schema export + schema validation fixtures.
- **Runtime Targets:** Python 3.11+ / Node.js 20+ / Chrome MV3 runtime.
- **Contract Tests:** `pytest` (Backend contract tests) and `vitest` (Extension contract tests).

---

## 3. Endpoints & Protocol Definition

Base URL: `http://localhost:8000/api/v1`

### 3.1 `POST /api/v1/translate` (Main Translation Endpoint)
- **Description:** Submit a manga page image for detection and translation.
- **Request Headers:** `Content-Type: application/json`
- **Request Body (`TranslationRequest`):**
  ```json
  {
    "image": "data:image/jpeg;base64,...",
    "image_hash": "a1b2c3d4...", 
    "source_lang": "auto",
    "target_lang": "vi",
    "engine": "auto",
    "provider": "gemini",
    "translator": "google-free",
    "force_refresh": false
  }
  ```
- **Response 200 OK (`TranslationResponse`):**
  ```json
  {
    "success": true,
    "page_hash": "a1b2c3d4e5f67890...",
    "engine_used": "cloud",
    "execution_time_ms": 1120,
    "from_cache": false,
    "blocks": [
      {
        "id": "blk_01",
        "box": [120, 450, 280, 720],
        "polygon": [
          [15.2, 5.1], [50.0, 2.0], [85.4, 6.2], [98.1, 40.5],
          [95.0, 78.2], [70.1, 95.0], [25.4, 98.2], [5.0, 65.0], [8.2, 25.1]
        ],
        "parent_bubble_id": null,
        "source_text": "何をしているんだ？",
        "translated_text": "Cậu đang làm cái gì thế?",
        "direction": "vertical",
        "confidence": 0.98
      }
    ]
  }
  ```

### 3.2 `GET /api/v1/cache/{image_hash}` (Lightweight Cache Lookup)
- **Description:** Check if a page is already cached in SQLite without sending Base64 image data.
- **Query Parameters:**
  - `target_lang` (string, default: `"vi"`)
  - `engine` (string, optional, default: `"auto"`)
- **Response 200 OK:** Same as `TranslationResponse` (with `"from_cache": true`).
- **Response 404 Not Found (`APIErrorResponse`):**
  ```json
  {
    "success": false,
    "error": {
      "code": "CACHE_MISS",
      "message": "Page has not been translated yet",
      "details": { "image_hash": "a1b2c3d4..." }
    }
  }
  ```

### 3.3 `GET /api/v1/health` (Health Check & Engine Discovery)
- **Description:** Extension probes backend availability and active engine status on load.
- **Response 200 OK:**
  ```json
  {
    "status": "ok",
    "version": "0.1.0",
    "engines_available": {
      "mock": true,
      "cloud": true,
      "local": true
    },
    "active_engine": "cloud"
  }
  ```

### 3.4 `POST /api/v1/models/discover` (Zero-Hardcoding Live Model Discovery)
- **Description:** Backend queries upstream provider catalog live and returns models with `supports_vision` tagging.
- **Request Body (`ModelDiscoveryRequest`):**
  ```json
  {
    "provider": "google",
    "api_key_override": null,
    "base_url_override": null
  }
  ```
- **Response 200 OK (`ModelDiscoveryResponse`):**
  ```json
  {
    "success": true,
    "provider": "google",
    "models": [
      {
        "id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "supports_vision": true
      }
    ]
  }
  ```

### 3.5 `GET/POST /api/v1/settings/providers` (In-Extension Key Governance)
- **`GET /api/v1/settings/providers`:** Returns masked key status (`AIzaSy...4xK8`) for all 4 providers (`google`, `openai`, `anthropic`, `custom`).
- **`POST /api/v1/settings/providers`:** Persists API key or Base URL updates into `.env` atomically via temporary file swap and updates memory settings.

---

## 4. Data Models & TypeScript Contracts

### 4.1 Bounding Box Coordinate System
- Format: `[ymin, xmin, ymax, xmax]`
- Constraints: All values must be integers between `0` and `1000`, with `ymin <= ymax` and `xmin <= xmax`.
- Client rendering formula:
  $$\text{top} = \frac{\text{ymin}}{1000} \times H_{\text{client}}, \quad \text{left} = \frac{\text{xmin}}{1000} \times W_{\text{client}}$$
  $$\text{height} = \frac{\text{ymax} - \text{ymin}}{1000} \times H_{\text{client}}, \quad \text{width} = \frac{\text{xmax} - \text{xmin}}{1000} \times W_{\text{client}}$$

### 4.2 Speech Bubble Polygon Coordinate System (Curved Contours)
- Format: Array of 18–25 2D vertices `[x, y]` representing simplified smooth bubble contours.
- Coordinate Space: **Local Relative Percentage (`0.0% – 100.0%`)** relative to the speech bubble bounding box `[xmin, ymin, xmax, ymax]`.
- Constraints: $x \in [0.0, 100.0]$, $y \in [0.0, 100.0]$.
- Client rendering formula (Direct CSS `clip-path` mapping):
  ```css
  clip-path: polygon(15.2% 5.1%, 50.0% 2.0%, 85.4% 6.2%, 98.1% 40.5%, ...);
  ```
- Rationale: Eliminates client-side coordinate recalculation. When the container `div` scales responsively on browser zoom, the polygon mask scales identically with zero geometric distortion.

### 4.3 TypeScript Type Definitions (`src/types/contract.ts`)

```typescript
export type BoundingBox = [number, number, number, number];

export type PolygonPoint = [number, number]; // [x, y] in range [0.0, 100.0] %

export type ReadingDirection = 'vertical' | 'horizontal';

export interface TranslatedBlock {
  id: string;
  box: BoundingBox;
  polygon?: PolygonPoint[]; // Optional 18-25 vertex contour in relative percentage
  parent_bubble_id?: string; // Optional grouping ID for merged connected bubbles
  source_text?: string;
  translated_text: string;
  direction?: ReadingDirection;
  confidence?: number;
}

export interface TranslationRequest {
  image: string;
  image_hash?: string;
  source_lang?: string;
  target_lang?: string;
  engine?: 'auto' | 'local' | 'cloud' | 'mock';
  provider?: 'google' | 'openai' | 'anthropic' | 'custom' | string;
  translator?: string;
  model?: string; // Chosen dynamic model identifier
  force_refresh?: boolean;
  chapter_url?: string;
}

export interface TranslationResponse {
  success: true;
  page_hash: string;
  engine_used: string;
  execution_time_ms: number;
  from_cache: boolean;
  blocks: TranslatedBlock[];
}

export interface APIErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

export interface APIErrorResponse {
  success: false;
  error: APIErrorDetail;
}
```

### 4.4 Python Pydantic Models (`src/backend/schemas/contract.py`)

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field

# Bounding box: [ymin, xmin, ymax, xmax] in 0-1000
Coordinate = Annotated[int, Field(ge=0, le=1000)]
BoundingBox = tuple[Coordinate, Coordinate, Coordinate, Coordinate]

# Polygon vertex: [x, y] in 0.0 - 100.0 percentage relative to box
RelativePercent = Annotated[float, Field(ge=0.0, le=100.0)]
PolygonPoint = tuple[RelativePercent, RelativePercent]

# SHA-256 Hex Hash: exactly 64 hexadecimal characters (prevents path traversal)
HashString = Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$", description="SHA-256 64-character hex digest")]


class TranslatedBlock(BaseModel):
    id: str = Field(description="Unique identifier for the block")
    box: BoundingBox = Field(description="[ymin, xmin, ymax, xmax] in 0-1000")
    polygon: list[PolygonPoint] | None = Field(
        default=None,
        description="18-25 vertices in 0-100% relative coordinates for clip-path mask",
    )
    parent_bubble_id: str | None = Field(
        default=None,
        description="Parent bubble identifier for merged connected speech balloons",
    )
    source_text: str | None = Field(default=None, description="OCR text detected")
    translated_text: str = Field(description="Translated text in target language")
    direction: Literal["vertical", "horizontal"] = Field(default="vertical")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TranslationRequest(BaseModel):
    # Max image payload size: ~15MB Base64 string length cap (20MB)
    image: str = Field(max_length=20_000_000, description="Base64 encoded image string or Data URL (max 15MB binary / 20MB Base64)")
    image_hash: HashString | None = Field(default=None, description="Precomputed SHA-256 hex digest")
    source_lang: str = Field(default="auto")
    target_lang: str = Field(default="vi")
    engine: Literal["cloud", "local", "local-manga", "local-rapid", "auto"] = Field(default="auto")
    force_refresh: bool = Field(default=False)


class TranslationResponse(BaseModel):
    success: Literal[True] = True
    page_hash: HashString
    engine_used: str
    execution_time_ms: int
    from_cache: bool = False
    blocks: list[TranslatedBlock]


class APIErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | list | str | None = None


class APIErrorResponse(BaseModel):
    success: Literal[False] = False
    error: APIErrorDetail
```

---

## 5. Standard Error Codes

All failures must return an `APIErrorResponse` with appropriate HTTP status codes:

| HTTP Status | Error Code (`code`) | Reason |
|---|---|---|
| `400` | `INVALID_IMAGE_PAYLOAD` | Base64 decode failed or unreadable image bytes |
| `404` | `CACHE_MISS` | Requested `image_hash` does not exist in SQLite cache |
| `413` | `PAYLOAD_TOO_LARGE` | Image payload exceeds maximum size limit (15MB binary / 20MB Base64) |
| `422` | `COORDINATE_OUT_OF_BOUNDS` | Bounding box value $<0$ or $>1000$, or $min > max$ |
| `422` | `INVALID_HASH_FORMAT` | Parameter `image_hash` does not match `^[a-fA-F0-9]{64}$` |
| `429` | `AI_RATE_LIMIT_EXCEEDED` | Upstream Cloud Vision (Gemini) quota exceeded |
| `500` | `ENGINE_EXECUTION_FAILED` | Internal error within OCR/translation pipeline |
| `503` | `LOCAL_ENGINE_UNAVAILABLE` | Local model files missing or failed to initialize |

---

## 6. Typography & Overlay Rendering Guidelines (Client Rule)

To prevent breaking words mid-character, clipping accents vertically, and eliminate XSS:
1. **Zero HTML Injection Policy (XSS Defense):** Extension **MUST** render `translated_text` using `element.textContent` or `element.innerText` exclusively. **NEVER** use `innerHTML` or `dangerouslySetInnerHTML`. Untrusted text from LLMs must always be treated as plain text.
2. **Two-Layer Rendering Architecture:**
   - **Layer 1 (Background Mask):** Dedicated `div` using `clip-path: polygon(...)` filled with white (#ffffff). Hugs author artwork contours and character pointer tails without bleeding onto hair or faces.
   - **Layer 2 (Text Container):** Positioned inside Inner Safe-Zone or child text box. **Not clipped** by `clip-path`, ensuring typography is never truncated.
3. **No Word Splitting:** Extension styles blocks with `word-break: keep-all; overflow-wrap: break-word; hyphens: none;`.
4. **Accent Safe Line Height:** Extension sets `line-height: 1.25` and `box-sizing: border-box`.
5. **Binary Search Font Fitting:** Extension iteratively checks `scrollHeight <= clientHeight` on each box during DOM mounting within bounds 10px to 22px.
5. **Adaptive Expansion:** If minimum font size `10px` is reached and text still exceeds client box, box expands up to $15\%$ horizontally/downward.

---

## 7. Network & Backend Security Controls

1. **Host Binding:** FastAPI MUST bind strictly to `127.0.0.1` (loopback). Never bind to `0.0.0.0`.
2. **CORS Restrictions:** Allow-Origin must NOT be `*`. Restrict to `chrome-extension://*` origins.
3. **Client Identification:** Require custom request header `X-InkShift-Client: extension` to prevent drive-by requests from arbitrary third-party websites.
4. **Decompression Bomb Guard:** Limit PIL max image pixels to `30_000_000` to prevent memory exhaustion bombs.

---

## 8. Testing Strategy

1. **Schema Integrity Tests (`tests/contract/test_schemas.py`):**
   - Verify Pydantic validates valid samples and rejects invalid coordinates ($>1000$, negative, or inverted bounds).
   - Verify `image_hash` regex rejects traversal strings (e.g., `../../etc/passwd`).
   - Verify oversized payloads (>20MB) are rejected with validation errors.
2. **TypeScript Fixture Validation (`tests/contract/test_types.ts`):**
   - Validate mock JSON responses match TypeScript interface definitions.
3. **Fixture Generation (`tests/fixtures/sample_page_response.json`):**
   - Provide standard Golden Master JSON response used by both backend mocks and extension tests.

---

## 9. Boundaries

- **Always:** Use integers `0–1000` for bounding boxes; validate request payloads at FastAPI route boundaries; return structured `APIErrorResponse`; use `textContent` in the Extension.
- **Ask First:** Adding new top-level endpoints; altering `TranslationResponse` block structure; introducing non-JSON transports.
- **Never:** Return unformatted Python stack traces in 500 errors; leak Gemini API keys in responses; bind to `0.0.0.0`; allow `innerHTML` in overlay DOM rendering.

---

## 9. Success Criteria

- [ ] SC-1: Pydantic models for `TranslationRequest`, `TranslationResponse`, and `APIErrorResponse` pass strict type checks (`mypy --strict`).
- [ ] SC-2: TypeScript interfaces matching the Pydantic schema compile with zero errors (`tsc --noEmit`).
- [ ] SC-3: Standard golden fixture (`sample_page_response.json`) validates against both Python and TypeScript contracts.
- [ ] SC-4: Coordinate validation rules strictly reject invalid ranges ($>1000$ or $<0$).
- [ ] SC-5: Error response structure is identical across all endpoints.
