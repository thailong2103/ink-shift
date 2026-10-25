# Rule: Documentation Lifecycle and Synchronization Protocol

> **Applies to:** All AI coding agents interacting with the InkShift repository.  
> **Purpose:** Ensure all documentation (Specs, ADRs, State Dashboard, Tasks) remains living, consistent, and strictly synchronized with implementation state without developer overhead.  

---

## 1. Documentation Hierarchy & File Conventions

All documentation follows an English-first Git-tracked model, with an optional parallel Vietnamese copy for local developer convenience:

| Document Type | Primary Path (Git Tracked) | Vietnamese Convenience (`.gitignore`) | Purpose |
|---|---|---|---|
| **Living Dashboard** | `docs/PROJECT_STATE.md` | `docs/vi/PROJECT_STATE.md` | Single-source-of-truth status, active milestone, tech stack, module graph, and active tasks. |
| **Capability Map** | `docs/specs/CAPABILITY_MAP.md` | `docs/vi/specs/CAPABILITY_MAP.md` | Decomposed modules, build order, and dependency graph. |
| **Module Spec** | `docs/specs/SPEC-<module>.md` | `docs/vi/specs/SPEC-<module>.md` | Technical specification, endpoints, models, boundaries, and acceptance criteria. |
| **Architecture Decision** | `docs/decisions/ADR-<NNN>-<title>.md` | `docs/vi/decisions/ADR-<NNN>-<title>.md` | Sequential record of architectural choices and trade-offs. |
| **Plan & Tasks** | `tasks/plan.md`, `tasks/todo.md` | — | Implementation roadmap and discrete executable task checklist. |

---

## 2. Specification Lifecycle & Approval Gates

Every module specification progresses through strict state gates:

```
[Draft] ──► [Proposed] ──► [Approved] ──► [Implemented]
```

1. **`Draft` / `Proposed`:**
   - Authored during Phase 1 (`spec-driven-development`).
   - Marked: `> **Status:** Proposed — Awaiting Human Developer Review`.
   - **Hard Rule:** Agents **CANNOT** write code, create tasks, or start implementation while status is `Proposed`.
2. **`Approved`:**
   - Set **ONLY** after explicit human developer sign-off in chat.
   - Marked: `> **Status:** Approved by Solo Developer (@human) on YYYY-MM-DD`.
   - Unlocks Phase 2 (Planning) and Phase 3 (Tasks breakdown).
3. **`Implemented`:**
   - Marked after all Success Criteria (SC-*) are verified and committed.
4. **Keeping the Spec Alive:**
   - If requirements or technical details change during implementation, **update the Spec first**, confirm with the human, and update code second. Never allow code and spec to diverge.

---

## 3. ADR (Architecture Decision Record) Lifecycle

ADRs capture the *why*, alternatives considered, and trade-offs:

1. **Mandatory Triggers:** An ADR must be proposed when:
   - Selecting or changing frameworks, libraries, or runtimes.
   - Defining public data contracts, schemas, or coordinate systems.
   - Deciding communication protocols (e.g., REST vs. SSE vs. WebSockets).
2. **State Progression:**
   - `Proposed` $\to$ `Accepted` (by human decision).
   - If a previous decision is superseded: mark `Superseded by ADR-XXX` (never delete old ADRs).
3. **Sequential Numbering:** Filenames must increment monotonically (`ADR-001`, `ADR-002`, `ADR-003`, ...).

---

## 4. Trigger Events: When to Update What

Agents must automatically perform documentation synchronization on these specific lifecycle events:

| Event / Trigger | Required Documentation Actions |
|---|---|
| **Human approves Spec** | 1. Change Spec status to `Approved`.<br>2. Update `docs/PROJECT_STATE.md` (active spec pointer).<br>3. Generate `tasks/plan.md` and `tasks/todo.md` for the module. |
| **ADR is decided & accepted** | 1. Save `docs/decisions/ADR-<NNN>-<title>.md` (and parallel `docs/vi/`).<br>2. Add entry to ADR table in `docs/PROJECT_STATE.md`.<br>3. Update Active Tech Stack table in `docs/PROJECT_STATE.md`. |
| **Task completed in `tasks/todo.md`** | 1. Mark checkbox `[x]` in `tasks/todo.md`.<br>2. If checkpoint reached, update active task line in `docs/PROJECT_STATE.md`. |
| **Module implementation complete** | 1. Update module status in `docs/PROJECT_STATE.md` Mermaid diagram (`#e8f5e9` solid green).<br>2. Mark milestone progress in Gantt chart.<br>3. Mark Spec status as `Implemented`. |

---

## 5. Consistency & Link Integrity Verification

Before concluding any session or completing a documentation task:
- Ensure all markdown links use standard syntax with `file:///` URLs or valid repo-relative paths.
- Ensure every English doc in `docs/` has its parallel Vietnamese copy in `docs/vi/` updated if created.
- Ensure `docs/PROJECT_STATE.md` can be read and understood by the developer in under 60 seconds.
