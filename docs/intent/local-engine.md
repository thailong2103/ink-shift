# Statement of Intent: Module 5 (`local-engine`)

> **Module ID:** `local-engine`  
> **Target Hardware:** AMD Ryzen 7 8845HS + AMD Radeon 780M (32GB RAM / UMA)  
> **Status:** Confirmed by Developer (@human)  
> **Date:** 2026-10-15  
> **Standard:** `interview-me` Output & Governance Contract  

---

## 1. Intent & Boundaries

- **Outcome:** Build a modular, on-device local manga translation engine (`local-engine`) composed of a Text Bubble Detector, a Swappable OCR Layer, and a Swappable Translation Layer, optimized for maximum speed on **AMD Ryzen 7 8845HS (Zen 4 AVX-512) and Radeon 780M (DirectML)**.
- **User:** Manga reader translating raw Japanese manga or multilingual comics (English/Chinese) directly with **Zero API Cost**, leveraging the host's AMD hardware and 32GB RAM without needing continuous cloud vision token spend.
- **Why now:** Foundation and Extension Core (Modules 0–4) are completed. InkShift needs an independent local engine to deliver the dual-engine capability promised in the architectural capability map.
- **Success Criteria:**
  1. Bubble Detector (`YOLO11s-seg` ONNX) + OCR inference runs via `onnxruntime-directml` (accelerated by Radeon 780M) and Zen 4 AVX-512 CPU fallback, achieving total page processing in $\le 1.0 - 2.0$ seconds.
  2. Swappable OCR interface supporting `manga-ocr` (Japanese Raw) and `RapidOCR` (English/Multilingual).
  3. Swappable Translation interface supporting Google Translate batch free API (default zero-cost) and Text LLM API (optional token-efficient).
- **Constraints:**
  - Operating system: Windows 11.
  - No NVIDIA CUDA dependencies (use Microsoft DirectML via `onnxruntime-directml`).
  - Take advantage of 32GB RAM to keep model weights permanently cached in memory for sub-second inference.
- **Out of scope:**
  - No model training from scratch.
  - No background inpainting / text erasing.
  - No CUDA-exclusive packages or Linux-only drivers.
