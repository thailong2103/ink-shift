# ADR-002: API Contract, Coordinate System, and Data Exchange Protocol

- **Status:** Accepted  
- **Date:** 2026-10-09  
- **Decision-Maker:** Solo Developer (human)  
- **Consulted:** AI Agent  
- **Target Module:** `api-contract` (Module 1 Foundation)  

---

## 1. Context & Problem Statement

InkShift connects a Chromium Browser Extension (TypeScript, Manifest V3) to a local AI Translation Engine backend (Python FastAPI). The system must support two interchangeable translation providers:
1. **Cloud Vision Turbo:** Gemini 2.0 Flash / OpenAI Vision (single-pass end-to-end detection and translation).
2. **Local Offline Pipeline:** Comic-Text-Detector + Manga-OCR + translation engine (sequential pipeline).

Without a rigid, strictly-typed data contract, changes to local models or cloud providers would cause breaking changes on the frontend overlay rendering. We need a definitive schema governing:
- Coordinate space and bounding box representation.
- Image payload encoding and transport.
- Communication protocol (Batch vs Streaming).
- Caching strategy and idempotency key for single-page reading.
- Text block representation accommodating Vietnamese word wrapping in vertical Japanese speech bubbles.

---

## 2. Options Considered

### A. Coordinate System
- **Option 1A (Selected):** Normalized Integer `[ymin, xmin, ymax, xmax]` in `[0, 1000]`.
  - *Pros:* Native Gemini Vision format; no floating-point rounding drifts; compact JSON; simple scaling formula `(val / 1000) * renderedDimension`.
  - *Cons:* Requires local detector adapter to map raw pixels to 1000-scale.
- **Option 1B:** Normalized Floats `0.0 - 1.0`.
  - *Pros:* Direct YOLO output.
  - *Cons:* Floating-point precision truncation, larger JSON payloads.
- **Option 1C:** Absolute Pixel Coordinates `[x, y, w, h]`.
  - *Cons:* Breaks on responsive images or CSS `object-fit: contain` resizing.

### B. Image Payload Transport
- **Option 2A (Selected):** Base64 String in JSON Body.
  - *Pros:* Pure JSON contract; trivial to log, test with Postman/pytest fixtures, and mock; ~2ms transfer latency over `localhost`.
  - *Cons:* 33% payload inflation (negligible on loopback).
- **Option 2B:** `multipart/form-data` binary upload.
  - *Cons:* Complex Pydantic model handling and harder fixture generation.
- **Option 2C:** Passing Image URL for Backend to download.
  - *Cons:* Fails on 80% of manga websites due to hotlinking protection, referer validation, or Cloudflare tokens.

### C. Communication Protocol
- **Option 3A:** REST Request/Response Batch only.
- **Option 3B:** Mandatory Server-Sent Events (SSE) immediately.
- **Option 3C (Selected):** REST Batch Core MVP with Stream-ready DTO.
  - *Pros:* Simpler, predictable client state machine; easy SQLite page-level caching; individual `TranslatedBlock` entities are modular, allowing an additive `/stream` endpoint later without breaking the contract.

### D. Caching & Idempotency Strategy
- **Option 4A + Two-Step Lookup (Selected):**
  - Backend computes SHA-256 over image bytes as primary cache key.
  - Client can execute a lightweight `GET /api/v1/cache/{image_hash}?target_lang=vi` (sending only a 64-char hex string) to avoid re-uploading 1.5MB Base64 when reading page-by-page.
  - `POST /api/v1/translate` supports `force_refresh: boolean` to bypass cache on manual user request.

### E. Text Entities & Vietnamese Bubble Rendering
- **Option 5 (Selected):** Contract provides `box`, `translatedText`, and optional `direction`. Extension handles styling:
  - Extension uses CSS `word-break: keep-all; overflow-wrap: break-word; line-height: 1.25;` to prevent breaking Vietnamese words in half and avoid vertical accent clipping.
  - Extension applies binary-search dynamic font fitting within the detected box.
  - Backend prompt enforces concise translation phrasing.

---

## 3. Decision & Rationale

We adopted **Options 1A, 2A, 3C, 4A (Two-step cache), and 5**:
1. **Coordinates:** Bounding box format is strictly `[ymin, xmin, ymax, xmax]` as integers between `0` and `1000`. Local engine adapters must normalize detector output to this scale.
2. **Payload:** Standard `POST /api/v1/translate` accepts JSON `{ "image": "data:image/...;base64,...", "target_lang": "vi", "force_refresh": false, ... }`.
3. **Cache Lookup:** Add lightweight `GET /api/v1/cache/{image_hash}` to optimize page-by-page reading.
4. **Text Integrity:** Extension owns UI typography, word boundary preservation, and auto-fitting; Backend owns concise translation output.

---

## 4. Consequences

- **Positive Impact:**
  - Frontend and Backend can be developed in complete parallel using mock fixtures matching this schema.
  - Zero coupling between Extension and AI engine choices (Cloud or Local).
  - Page-by-page reading achieves sub-millisecond cache hits without unnecessary data transfer.
  - Vietnamese text rendering will never break words or clip accents.
- **Trade-offs / Negatives:**
  - Local engine requires an adapter conversion step (raw pixel $\to$ 1000-scale).
  - Base64 encoding increases memory overhead slightly on the client during page processing.
- **Follow-up Tasks:**
  - Create formal specification `docs/specs/SPEC-api-contract.md`.
  - Update `docs/PROJECT_STATE.md`.
