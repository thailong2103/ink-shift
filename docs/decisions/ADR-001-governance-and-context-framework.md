# ADR-001: Repository-Native Governance and Agent Context Framework

- **Status:** Accepted  
- **Date:** 2026-10-08  
- **Decision-Maker:** Solo Developer (human)  
- **Consulted:** AI Agent  
- **Target Module:** `sdlc-governance` (Module 0)  

---

## 1. Context & Problem Statement

In solo human-agent software development for InkShift (a 4-week build), three persistent failure modes occur:
1. **Context Loss Between Sessions:** Agents lose memory of tech stack choices, module relationships, and progress across disconnected chat sessions.
2. **Autonomous Decisions:** Agents autonomously select libraries, schemas, or architectural patterns without developer approval.
3. **Silent Assumption-Filling:** Agents silently resolve ambiguities rather than pausing to verify intent with the developer.

We need a lightweight governance and context protocol that acts simultaneously as a developer dashboard and as an agent bootstrapping protocol.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A: External Project Tools (Linear / Jira / Notion)** | Familiar UI, rich issue tracking widgets | High context switching overhead for solo dev; agents cannot easily read private web interfaces without external API keys/MCP | Not recommended for 4-week solo scope |
| **Option B: Pure In-Chat Context (No Persistent Docs)** | Zero setup time, quick start | High risk of hallucination, context drift, duplicate work, and repeated explanations every session | Not recommended |
| **Option C: Repository-Native Markdown System (`docs/`, `AGENTS.md`, `tasks/`)** | 100% version-controlled with code; zero friction for agent ingestion; readable by developer in < 60 seconds; no third-party dependencies | Requires discipline to update docs when tasks complete | **Recommended & Selected** |

---

## 3. Decision & Rationale

We chose **Option C: Repository-Native Markdown System**.

### Key Rules Established:
1. **Decision Authority Boundary:** *"The agent proposes; the human decides. No exceptions."* All technology choices, libraries, schemas, and architectural boundaries must be explicitly approved by the human developer.
2. **Sequential ADR Numbering:** Architectural choices will be captured sequentially as `ADR-001`, `ADR-002`, etc., in `docs/decisions/`.
3. **Single Source of Truth Dashboard:** `docs/PROJECT_STATE.md` serves as the living dashboard tracking timeline, tech stack, and module maps.
4. **Agent Bootstrap Entrypoint:** Root `AGENTS.md` and `.agents/rules/` serve as the mandatory initial context loaded by agents upon session startup.

---

## 4. Consequences
- **Positive Impact:**
  - Zero context loss across sessions: agents read `docs/PROJECT_STATE.md` and `AGENTS.md` to instantly synchronize state.
  - Architecture integrity preserved: no unapproved libraries or architectural drift can be introduced.
  - Complete history of decisions tracked directly in Git alongside source code.
- **Trade-offs / Negatives:**
  - Every major architectural decision requires writing an ADR and updating the state document.
- **Follow-up Tasks:**
  - Create `docs/PROJECT_STATE.md`.
  - Create root `AGENTS.md` and `.agents/rules/`.
  - Verify and initialize Git baseline commit.
