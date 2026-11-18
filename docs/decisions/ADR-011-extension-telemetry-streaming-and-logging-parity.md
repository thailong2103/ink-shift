# ADR-011: Extension Telemetry Streaming and Sub-Millisecond Logging Parity

- **Status:** Accepted
- **Date:** 2026-10-22
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** Antigravity AI Agent
- **Related Spec / Feature:** Phase 23 (`docs/specs/SPEC-extension-core.md`, `docs/specs/SPEC-backend-engine.md`)

---

## 1. Context & Problem Statement

Prior to Phase 23, observability across InkShift suffered from two operational limitations:
1. **Timestamp Precision & Format Disparity:** Python backend logs in `inkshift.log` printed standard second-level timestamps (`%Y-%m-%d %H:%M:%S`), while browser DevTools output ISO strings or unformatted console messages. When debugging latency spikes across prefetch and translation, millisecond events could not be chronologically correlated.
2. **Log Destination Contention:** Content scripts and service workers ran asynchronously inside the browser sandbox without direct access to local disk logs. Attempting to flush extension logs into the primary backend log (`data/logs/inkshift.log`) caused interleaving and chronological inversion due to network batch debounce delays.
3. **Network Overhead Risk:** High-frequency logging from DOM mutation observers and image scanners threatened to flood backend network sockets if sent per-event.

We required an isolated, low-overhead telemetry ingestion pipeline that captures extension lifecycle events with sub-millisecond precision without degrading translation latency.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Direct File Append via Native Messaging** | - Direct disk write from extension.<br>- True zero network overhead. | - Requires complex native messaging host manifest and binary installer.<br>- Platform-specific Windows setup.<br>- Heavy friction for solo developer workflow. | Rejected |
| **Option 2: Immediate HTTP POST per Log Event into `inkshift.log`** | - Immediate delivery.<br>- Single unified log file. | - Network storm (dozens of requests/second during scroll).<br>- Batch flush reordering in `inkshift.log`.<br>- Degrades manga translation bandwidth. | Rejected |
| **Option 3: Service Worker Ring Buffer + Dedicated `extension.log`** | - Ring buffer (100 items) drops oldest logs on overflow.<br>- Debounced flush (1.5s or $\ge 10$ items); immediate flush on `ERROR`.<br>- Dedicated `data/logs/extension.log` preserves physical line sequence.<br>- Sub-millisecond formatting parity (`.%(msecs)03d` and `[HH:mm:ss.SSS]`).<br>- Correlation via `trace_id`. | - Creates a second log file to monitor.<br>- Telemetry events delayed up to 1.5s under normal reading. | **Accepted (Recommended)** |

---

## 3. Decision & Rationale

The developer approved **Option 3: Service Worker Ring Buffer + Dedicated `extension.log`**:

1. **Sub-Millisecond Precision Parity:**
   - Backend `src/backend/logging.py`: Configured `RotatingFileHandler` with `"%(asctime)s.%(msecs)03d [%(levelname)-7s] [%(name)s] %(message)s"`.
   - Extension `src/extension/shared/extension_logger.ts`: Outputs `[HH:mm:ss.SSS] [InkShift:<MODULE>] <message>`.
2. **Dedicated Log File Separation:**
   - Backend routes `inkshift.extension.*` log records exclusively to `data/logs/extension.log`.
   - Eliminates batch-flush interleaving in `data/logs/inkshift.log`, maintaining physical line order in both files.
3. **Centralized Service Worker Batcher (`TelemetryBatcher`):**
   - Content Script and Popup forward log events to Service Worker via IPC (`FORWARD_TELEMETRY`).
   - In-memory ring buffer limits heap usage to $\le 100$ items.
   - Routinely flushes every $1500\text{ms}$ or upon reaching 10 items.
   - Flushes immediately out-of-band upon encountering `ERROR` level logs.
4. **Fire-and-Forget Ingestion:**
   - Gateway client silently catches network failures to guarantee telemetry never breaks core translation.

---

## 4. Consequences

- **Positive Impact:**
  - Full end-to-end traceability of prefetch pipeline, cache hits, DOM scans, and translation dispatches.
  - Sub-millisecond precision enables pinpoint latency profiling across frontend and backend boundaries.
  - Zero performance degradation on manga reading workflows.
- **Trade-offs / Negatives:**
  - Developers monitor two separate log files (`data/logs/inkshift.log` for backend, `data/logs/extension.log` for extension).
- **Follow-up Tasks:**
  - Verified with 22 Vitest test suites (194 tests) and backend telemetry API unit tests (`tests/backend/test_telemetry_api.py`).
