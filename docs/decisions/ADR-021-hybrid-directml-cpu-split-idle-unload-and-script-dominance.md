# ADR-021: Hybrid DirectML/CPU Execution Split, `limit_side_len=1280`, Idle Auto-Unload & Dominant-Script Language Detection

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

Following the Phase 46–47 stabilization of the unified `YOLO11s-seg + PP-OCRv6_medium` pipeline and 2D spatial clustering, hardware profiling on the target workstation (AMD Ryzen 7 8845HS APU + Radeon 780M RDNA 3 iGPU with 32 GB Unified Memory) revealed two compounding operational and accuracy defects:

1. **DirectML DBNet VRAM Bloat Violated the $\le 2048\text{ MB}$ Memory Budget:**
   - Running all three ONNX Runtime sessions (`YOLO11s-seg`, `PP-OCRv6_det_medium`, `PP-OCRv6_rec_medium`) on `DmlExecutionProvider` with `limit_side_len=1920` peaked at **3,114–3,309 MB** combined GPU VRAM (Dedicated + Shared) on high-resolution pages (`2039×2880`) and **1,929 MB** GPU VRAM on standard `1125×1600` pages — driven almost entirely by DBNet (`PP-OCRv6_det_medium`) allocating **+2,430.5 MB** GPU Shared workspace tensors in DirectML.
   - Because ONNX Runtime sessions remained resident indefinitely after inference completed, >1.9–3.3 GB GPU VRAM remained locked even while idle, preventing local LLM runtimes (e.g., LM Studio) from loading large models simultaneously.
   - Note: Empirical testing also confirmed that disabling ONNX Runtime arena memory reuse (`enable_mem_reuse=0`) doubled per-page DirectML latency (~776 ms $\to$ 1,812 ms) while freeing **0 MB** of GPU VRAM, ruling out naive arena-disable flags.

2. **`limit_side_len=1920` Noise Hallucination Triggered `detect_page_language()` Misclassification:**
   - On real `1125×1600` English manga pages, upscaling/running DBNet at `limit_side_len=1920` produced spurious tick detections on background artwork and misread a small handwritten `"I... I..."` dialogue box as `'工工'` (2 Hanzi characters).
   - Meanwhile, `OCRRouter.detect_page_language()` checked `if hanzi_count >= 2: return "zh"` unconditionally before checking `latin_count` (~280 English letters on the page), misclassifying the entire English page as Chinese (`"zh"`).
   - Lowering `limit_side_len` too aggressively to `960` saved VRAM only slightly on DirectML while dropping legitimate small text boxes (`15/16` blocks), whereas `limit_side_len=1280` preserved **16/16** boxes cleanly with zero background noise.

The architecture therefore required an execution-provider split, input-resolution tuning, bounded idle session lifecycle management, and proportional script dominance logic.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Keep Full DirectML (`limit_side_len=1920`)** | - Simple uniform `DmlExecutionProvider` config<br>- Fastest warm single-page GPU compute (~1.05s on 1125×1600) | - **1.93–3.31 GB** GPU VRAM peaks break the $\le 2048\text{ MB}$ budget (`SC-5`)<br>- Collides with local LLM weights<br>- Hallucinates background ticks and `'工工'` | Not recommended |
| **Option 2: Full DirectML (`limit_side_len=1280`)** | - Fastest warm latency (~0.88s/page on 1125×1600)<br>- Clean 16/16 detection | - Still consumes **~1.89 GB** GPU VRAM per session and leaves VRAM locked permanently when idle | Fallback preset via `.env` (`INKSHIFT_LOCAL_EXECUTION_PROVIDER=directml`) |
| **Option 3: Pure CPU Execution (`CPUExecutionProvider`, 8 threads)** | - **0 MB** GPU VRAM usage | - ~2.17s/page warm latency (~2× slower than GPU-assisted execution)<br>- Under-utilizes onboard RDNA 3 GPU for YOLO11 and PP-OCRv6_rec | Fallback preset via `.env` (`INKSHIFT_LOCAL_EXECUTION_PROVIDER=cpu`) |
| **Option 4 (Chosen): Hybrid (`DET` CPU + `YOLO`/`REC` DirectML) + `limit_side_len=1280` + Idle Auto-Unload (`180s`) + Dominant-Script `detect_page_language()`** | - Locks active GPU VRAM at **~608 MB** regardless of image resolution<br>- Keeps fast **~1.00–1.22s/page** warm throughput<br>- Automatically unloads idle sessions to **~22 MB** GPU VRAM after 180s (`PriorityLocalLock`-safe)<br>- Accurately achieves 16/16 English recall and resists stray false-positive CJK chars | - Slightly slower (~170 ms/page vs full DirectML at 1280) due to CPU DBNet execution<br>- First request after idle unload incurs cold reload latency (~1–2s) | **Recommended (Adopted as Default)** |

---

## 3. Decision & Rationale

The developer approved **Option 4** across backend runtime, configuration, and language-detection layers:

1. **Hybrid Execution Mode (`INKSHIFT_LOCAL_EXECUTION_PROVIDER=hybrid`, new default):**
   - `YOLO11Detector` (`yolo11s-seg.onnx`) and `RapidOCRAdapter` recognizers (`PP-OCRv6_rec_medium.onnx`, lazy `korean_PP-OCRv5_rec_mobile.onnx`) execute on **`DmlExecutionProvider`** with `SessionOptions(enable_mem_pattern=False, execution_mode=ORT_SEQUENTIAL)` (preserving DirectML arena reuse so speed remains intact).
   - `PP-OCRv6_det_medium.onnx` (DBNet) executes on **`CPUExecutionProvider`** with bounded `intra_op_num_threads` (`INKSHIFT_LOCAL_CPU_THREADS`, default `min(8, max(1, os.cpu_count() or 4))`), eliminating the +2.43 GB DBNet DirectML workspace spike while holding active GPU VRAM steady at **~608 MB**.
   - Preserves `"directml"` and `"cpu"` modes via `INKSHIFT_LOCAL_EXECUTION_PROVIDER` overrides.

2. **Configurable `limit_side_len=1280` (`INKSHIFT_LOCAL_OCR_DET_LIMIT_SIDE_LEN`, default `1280`):**
   - Replaces hardcoded `1920` in `RapidOCRAdapter._ensure_det_and_rec()`. Balances sharp small-bubble recall (`16/16` on real MangaDex pages) against background line noise suppression.

3. **Bounded Idle Auto-Unload (`INKSHIFT_LOCAL_IDLE_UNLOAD_SECONDS`, default `180.0`, `0` disables):**
   - Both `YOLO11Detector` and `RapidOCRAdapter` record monotonic last-used timestamps and expose `is_loaded` plus `unload_session()` / `unload_sessions()` (resetting lazy state including `_ko_load_attempted`, calling `gc.collect()`, and preserving unit-test-injected mock sessions).
   - FastAPI `lifespan()` spawns a lightweight async watcher task gated by `PriorityLocalLock` (checking `not local_lock.locked()` and acquiring at lowest `"P2"` priority with double-checked timestamps) so active translations are never interrupted and idle GPU VRAM drops to **~22 MB** within 3 minutes of inactivity.

4. **Dominant-Script Language Detection (`OCRRouter.detect_page_language()`):**
   - Requires Latin dominance (`latin_count >= 8` and `(cjk_total == 0 or latin_count >= cjk_total * 4)`) before evaluating CJK thresholds, while also resolving `ko` vs `ja` vs `zh` competitively by dominant script count. Stray noisy Hanzi/Hangul characters on an English or Japanese page can no longer hijack page-level language classification, while genuine CJK pages containing English product names (e.g., `"Apple iPhone Pro"`) remain classified cleanly in CJK.

---

## 4. Consequences

- **Positive Impact:**
  - Satisfies the `CONSTRAINTS.md` (`<= 2048 MB`) and `SPEC-manga-context-graph.md` **`SC-5`** hardware memory budget with >3× headroom (**~608 MB** active vs 2,048 MB limit, **~22 MB** idle).
  - Unblocks concurrent GPU workloads (LM Studio / Ollama) automatically after 180 seconds of reading inactivity without restarting the InkShift server.
  - Eliminates false `'zh'` routing on English manga pages caused by small-text OCR hallucinations.
- **Trade-offs / Negatives:**
  - Resuming reading after >180 seconds idle incurs a ~1–2 second one-time lazy session re-initialization delay.
  - CPU DBNet inference adds ~170–340 ms per page compared to unconstrained DirectML (`~1.00–1.22s` total vs `~0.88s`), still comfortably within the `<= 5000 ms` local latency budget.
- **Follow-up Tasks:**
  - Verify automated unit/integration suites and live hardware benchmark measurements under `CONSTRAINTS.md`. *(Verified: 375 backend pytest tests, 0 mypy strict errors, 0 ruff lint errors on touched files, live benchmark on 1125×1600 page measured **608.0 MB** active GPU VRAM, **14.4 MB** idle GPU VRAM after unload, zero-leak reload back to **608.0 MB**, and accurate `"en"` classification).*
  - Keep `SPEC-local-engine.md`, `SPEC-manga-context-graph.md` (`SC-5`), `README.md`, `README.vi.md`, `.env.example`, and local dashboards synchronized.
