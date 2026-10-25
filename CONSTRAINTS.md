# Constraints: InkShift Quality Bar & Engineering Boundaries

> **Status:** Active  
> **Last reviewed:** 2026-10-09 by Solo Developer (@human)  
> **Rule:** *Read CONSTRAINTS.md before writing code. Do not weaken it to make a change pass.*

---

## 1. Floor (Always Enforced, No Exceptions)

Every agent and human commit must satisfy the Floor without exception:

- **No new suppression comments:** `@ts-ignore`, `@ts-expect-error`, `eslint-disable`, `# noqa`, `# type: ignore`.
- **No unimplemented stubs:** `throw new Error("Not implemented")`, empty `catch {}`, `pass` or `TODO` replacing working logic.
- **No skipped or deleted tests:** No `.skip()`, no deleted tests without explicit reason documented in commit messages.
- **No secrets in source:** No API keys, credentials, or secrets in source code or git history (especially Gemini API keys, OpenAI tokens).
- **No autonomous relaxing of constraints:** This file is never modified or weakened to make failing checks pass.

---

## 2. Enforced Dimensions (Target Numbers)

When checks fail mid-task, the agent **MUST BLOCK** immediately, address the root cause, and verify green status before completing the task.

| Dimension | Rule | Checked by | Runs at |
|---|---|---|---|
| **Floor Guard** | Zero suppression comments, stubs, deleted tests, or secrets | Reference floor-guard script / `git diff` | Every edit (`check:fast`) |
| **Types (Extension & Web)** | Zero type errors | `tsc --noEmit` | Every edit (`check:fast`) |
| **Types (Python Backend)** | Zero type errors (`--strict`) | `mypy src/` | Every edit (`check:fast`) |
| **Lint & Formatting** | Zero errors from project rules | `ruff check src/` / `biome check` | Every edit (`check:fast`) |
| **Secrets in Source** | Zero secret leaks detected | `gitleaks detect --redact --no-banner` | Every edit (`check:fast`) |
| **Test Coverage (Changed Lines)** | $\ge 80\%$ test coverage on newly added or modified lines | `pytest --cov` / `vitest run --coverage` + git diff | Task completion (`check:task`), CI |
| **Architecture Boundaries** | Zero cross-module boundary violations (e.g., Extension calling direct AI APIs without backend/contract; engine skipping `BaseTranslationEngine`) | Contract test suite & import validator | Task completion (`check:task`), CI |
| **Security: Code** | Zero high or critical vulnerabilities | `semgrep scan --config p/default` | Full check (`check:full`), CI |
| **Security: Dependencies** | Zero high or critical known CVEs | `osv-scanner scan source -r .` | Full check (`check:full`), CI |

---

## 3. Execution Lifecycle & Time Budgets

To keep developer experience and agent loops fast and predictable, checks are strictly staged:

| Phase | Script Target | Scope & Actions | Time Budget |
|---|---|---|---|
| **EDIT (Fast)** | `check:fast` | Types (`tsc`/`mypy`), Lint, Secrets (`gitleaks`), Floor guard | $\le 5$ seconds |
| **TASK (Verify)** | `check:task` | `check:fast` + Unit/Contract test suite + Diff-scoped coverage ($\ge 80\%$) + Architecture boundaries | $\le 90$ seconds |
| **FULL (Review / CI)** | `check:full` | `check:task` + Semgrep code scan + OSV dependency scanner | Unmetered (CI / Pre-release) |

---

## 4. Measured, Not Yet Enforced (Ratchets & Milestones)

These metrics are tracked during development. Once baseline numbers are measured, ratchets will be set so they cannot degrade:

| Metric | Baseline | Target Threshold | Direction | Measurement Method |
|---|---|---|---|---|
| **Cloud Vision Translation Latency** | Greenfield (TBD) | $\le 2000$ ms per manga page | Must not grow | Automated benchmark fixture |
| **Local OCR Pipeline Latency** | Greenfield (TBD) | $\le 5000$ ms per manga page | Must not grow | Automated benchmark fixture |
| **Local Engine Memory Footprint** | Greenfield (TBD) | $\le 2048$ MB RAM / VRAM | Must not grow | Resource monitor profiling |
| **Extension Overlay Render Overhead** | Greenfield (TBD) | $\le 16$ ms (60 fps frame budget) | Must not grow | Browser performance profile |

---

## 5. Exceptions Log

Any temporary exception must have an explicit reason, an owner, and an expiry date ($\le 90$ days).

| ID | Rule | Target Path | Reason | Owner | Expiration |
|---|---|---|---|---|---|
| *(None)* | - | - | - | - | - |
