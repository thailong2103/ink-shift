# Spec: Project Governance & Agent Context System

> **Status:** Approved  
> **Date:** 2026-10-08  
> **Target Module ID:** `sdlc-governance`  
> **Source Intent:** [sdlc-governance.md](../intent/sdlc-governance.md)  
> **Decision-maker:** Solo Developer (human)  

---

## 1. Objective

Build a lightweight, repo-native governance and AI agent context framework for the **InkShift** project. This system solves three critical collaboration breakdowns identified in human-agent pairing:
1. **Context loss between sessions:** Agents re-asking, duplicating code, or forgetting previous architectural decisions.
2. **Autonomous decision-making:** Agents picking unapproved libraries, mechanisms, or patterns without developer consent.
3. **Silent assumption-filling:** Agents silently making assumptions in ambiguous scenarios rather than pausing and consulting the human developer.

The system simultaneously functions as:
- **A Developer Dashboard:** Giving the solo developer instant visibility into project progress, active tech stack, module relationships, and next tasks in < 60 seconds.
- **An Agent Context Protocol:** Supplying every new agent session with an unambiguous bootstrap procedure, explicit decision authority boundaries ("Agent proposes, human decides"), and single-source-of-truth project state.

---

## 2. Tech Stack & Formats

- **Documentation Format:** GitHub-Flavored Markdown (`.md`) formatted for optimal LLM context ingestion (dense, structured headers, clear bullet points, no conversational fluff).
- **Diagramming Standard:** Native Mermaid (`mermaid`) fenced blocks for module dependency graphs, data flows, and state machines.
- **Agent Rules Engine:** Root `AGENTS.md` and modular `.agents/rules/*.md` files compatible with Antigravity and modern agentic coding systems.
- **Storage & Version Control:** 100% repository-native (`git`). No external tools (no Jira, Linear, Confluence, or Notion).
- **Language:** English for all documentation, specs, ADRs, and tasks (ensures maximum token efficiency and instruction-following consistency for LLMs).

---

## 3. Commands

| Purpose | Executable Command | Description |
|---|---|---|
| **Version Control Init** | `git init` | Initialize local Git repository if not already present |
| **Status Check** | `git status` | Verify working tree clean/dirty status |
| **History Inspection** | `git log --oneline -n 10` | Review recent commit milestones and governance updates |
| **Doc Integrity Lint (Optional)** | `npx markdownlint-cli "docs/**/*.md" "AGENTS.md"` | Check markdown formatting consistency across governance docs |

---

## 4. Project Structure

The governance system establishes this standardized workspace layout:

```text
c:/Vide_coding/ink-shift/
├── .gitignore                               # Standard git ignore file
├── AGENTS.md                                # Root bootstrap instruction file for all AI agents
├── .agents/
│   ├── rules/
│   │   ├── decision-authority.md            # Enforces "Agent proposes, human decides" and boundary rules
│   │   └── context-loading.md               # Mandatory session initialization checklist
│   └── plugins/                             # Project agent plugins and skills
├── docs/
│   ├── PROJECT_STATE.md                     # Single-source-of-truth living dashboard & module map
│   ├── intent/
│   │   └── sdlc-governance.md               # High-level goals & product intents from human interviews
│   ├── specs/
│   │   └── SPEC-governance-system.md        # Technical specification for this governance framework
│   └── decisions/
│       ├── template.md                      # Standardized ADR template
│       └── ADR-001-governance-structure.md  # Architectural Decision Record for doc structure
└── tasks/
    ├── plan.md                              # Current phase technical implementation plan
    └── todo.md                              # Active task list with explicit acceptance & verification gates
```

---

## 5. Code & Document Style

### 5.1 Architecture Decision Record (ADR) Pattern
All architecture, tech stack, and pattern choices must follow the standardized ADR structure in `docs/decisions/` with sequential 3-digit identifiers (`ADR-001-<name>.md`):

```markdown
# ADR-[000]: [Decision Title]

- **Status:** Proposed | Accepted | Rejected | Superseded
- **Date:** YYYY-MM-DD
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

## Context & Problem Statement
[What problem requires a decision? What are the constraints?]

## Options Considered
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| Option A: [...] | [...] | [...] | [...] |
| Option B: [...] | [...] | [...] | [...] |

## Decision & Rationale
[What did the human decide and why?]

## Consequences
- **Positive:** [...]
- **Negative / Trade-offs:** [...]
```

### 5.2 Agent Decision Boundary Style
When an agent encounters an architectural, technical, or dependency choice:
1. Agent **CANNOT** make the choice or start coding.
2. Agent **MUST** pause execution and present options in this structured format:

```markdown
PROPOSAL FOR HUMAN DECISION:
- **Decision Required:** [e.g., State management approach for Feature X]
- **Options:**
  1. Option 1: [Details + Trade-offs]
  2. Option 2: [Details + Trade-offs]
- **Agent Recommendation:** [Recommended option and technical reasoning]
→ Human developer approval required before implementation.
```

### 5.3 Living Dashboard Pattern (`docs/PROJECT_STATE.md`)
Maintained as a concise, high-density status document containing:
1. **Current Milestone & 4-Week Timeline Tracker** (Solo developer pace).
2. **Active Tech Stack Table** (Language, Framework, Storage, Tooling).
3. **Module Dependency Map** (Mermaid diagram showing which parts exist and connect).
4. **Active Work & Queue** (Pointer to `tasks/todo.md`).
5. **Decisions Log Index** (Chronological links to all ADRs).

---

## 6. Testing & Verification Strategy

Since this is a documentation & process governance system rather than application runtime code, verification focuses on deterministic compliance:

| Concern | Verification Method | Pass Criteria |
|---|---|---|
| **Session Bootstrap Verification** | Simulate new agent session initialization | Agent immediately references `AGENTS.md` and `docs/PROJECT_STATE.md` before answering or planning |
| **Decision Authority Gating** | Prompt agent with an ambiguous library choice | Agent stops, presents options with trade-offs, and waits for human input without writing code |
| **Link Integrity** | Filepath verification check | All file links between `AGENTS.md`, `PROJECT_STATE.md`, specs, and ADRs use valid absolute/relative paths |
| **Task State Integrity** | End-of-task review | When a task is marked `[x]` in `tasks/todo.md`, `docs/PROJECT_STATE.md` is updated to reflect the new state |

---

## 7. Boundaries

### Always Do
- Read `AGENTS.md` and `docs/PROJECT_STATE.md` at the start of every session to establish ground truth.
- Follow the principle: **"The agent proposes; the human decides. No exceptions."**
- State assumptions explicitly with an `ASSUMPTIONS I'M MAKING:` block whenever ambiguity is detected.
- Record all architecture, library, and schema choices in `docs/decisions/` before code implementation using sequential IDs (`ADR-001`, `ADR-002`, ...).
- Keep documentation lightweight and easy to edit; prioritize clarity over ceremonial enterprise processes.

### Ask First
- Adding any new third-party dependency or external library.
- Modifying core application architecture, data schema, or module contracts.
- Altering the documentation directory hierarchy or governance protocols.
- Advancing from Phase 1 (Specify) to Phase 2 (Plan) or Phase 4 (Implement) without explicit human sign-off.

### Never Do
- Silently assume or guess developer preferences on ambiguous requirements.
- Autonomously select and install libraries or frameworks without prior human sign-off.
- Overwrite or delete incomplete tasks in `tasks/plan.md` or `tasks/todo.md` without explicit confirmation.
- Introduce complex enterprise agile tooling (Jira, Linear, heavy PR workflows) that adds friction to a 4-week solo build.

---

## 8. Success Criteria

- [x] **SC-1 (Spec Document):** `docs/specs/SPEC-governance-system.md` is reviewed and approved by the human developer.
- [x] **SC-2 (Agent Rules Entrypoint):** Root `AGENTS.md` and `.agents/rules/` are created, codifying the Decision Authority Model and session bootstrap procedure.
- [x] **SC-3 (Single Source of Truth Dashboard):** `docs/PROJECT_STATE.md` is created with current milestone, tech stack, and module map.
- [x] **SC-4 (Decision Record Framework):** `docs/decisions/template.md` and initial foundational record `ADR-001-governance-and-context-framework.md` are documented.
- [x] **SC-5 (Task Management Convention):** `tasks/` directory is established with templates for `plan.md` and `todo.md`.
- [x] **SC-6 (Review Time):** The developer can view `docs/PROJECT_STATE.md` at any time and understand current progress and next steps in under 60 seconds.

---

## 9. Decisions Confirmed by Developer

### Confirmed Decisions (2026-10-08):
1. **Git Initialization:** Approved. Repository will be initialized locally (`git init`) with a clean `.gitignore`.
2. **ADR Naming:** Approved sequential 3-digit numbering (`ADR-001-<name>.md`).
3. **Application Domain:** Scope isolated to completing Module 0 (Governance & Context System) first before specifying application feature code.

