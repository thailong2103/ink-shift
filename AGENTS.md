# InkShift — Agent Context & Governance Protocol

> **CRITICAL RULE:** The agent proposes; the human decides. No exceptions.

Welcome to the **InkShift** codebase. Every AI coding agent starting a session in this repository **MUST** follow this protocol before performing any task.

---

## 1. Mandatory Session Bootstrap Workflow

At the very beginning of **EVERY** session, perform these steps in order:

1. **Read Current State:** Inspect [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) to understand current milestone, active tech stack, module connections, and active tasks.
2. **Read Constraints:** Read [CONSTRAINTS.md](CONSTRAINTS.md) before writing code. Do not weaken it to make a change pass.
3. **Read Active Tasks:** Check [tasks/todo.md](tasks/todo.md) to see what is currently in flight.
4. **Verify Git State:** Run `git status` to ensure the working tree is clean.
5. **Synchronize:** Confirm your understanding of the active task before generating code or modifying architecture.

---

## 2. Decision Authority Model

Strict roles govern human-agent collaboration in InkShift:

### The Human Developer (Sole Decision-Maker)
- Makes **ALL** architecture, design, and tech stack choices.
- Approves or rejects every external library, dependency, database schema, and public API boundary.
- Signs off on specifications in `docs/specs/` before implementation begins.
- Signs off on ADRs in `docs/decisions/`.

### The AI Agent (Advisor & Executor)
- **CAN:** Propose architectures, evaluate trade-offs, identify edge cases, write tests, implement approved tasks.
- **CAN:** Push back if a proposed direction contradicts stated project intents or constraints.
- **CANNOT:** Introduce new dependencies, libraries, frameworks, or database engines without explicit human approval.
- **CANNOT:** Make design or architectural decisions autonomously.
- **CANNOT:** Silently fill in ambiguous requirements. When ambiguity is detected, **STOP** and present clarifying questions.

---

## 3. How to Propose Architectural Choices

When a technical choice arises (e.g., choosing a library, state pattern, or storage approach):
1. **DO NOT** make the choice or start implementing.
2. **STOP** and present options to the developer using this structured format:

```markdown
PROPOSAL FOR HUMAN DECISION:
- **Decision Needed:** [e.g., Choice of UI styling library]
- **Options Considered:**
  | Option | Pros | Cons | Recommendation |
  |---|---|---|---|
  | Option A: [...] | [...] | [...] | [...] |
  | Option B: [...] | [...] | [...] | [...] |
- **Agent Recommendation:** [Option and technical rationale]
→ Please confirm your decision before proceeding.
```
3. Once the human decides, document the result in `docs/decisions/ADR-[NNN]-[title].md` using [docs/decisions/template.md](docs/decisions/template.md).

---

## 4. Operational Boundaries

### Always Do:
- Read [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) at session start.
- Read [CONSTRAINTS.md](CONSTRAINTS.md) before writing code. Do not weaken it to make a change pass.
- State assumptions explicitly with an `ASSUMPTIONS I'M MAKING:` block when requirements need validation.
- Keep documentation lightweight, English-first (tracked in Git under `docs/`), with optional parallel Vietnamese copy in `docs/vi/` (local developer convenience, ignored via `.gitignore`).
- Update [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) and [tasks/todo.md](tasks/todo.md) when tasks complete.

### Ask First:
- Adding any new `npm` / third-party package or dependency.
- Modifying directory layout or project structure.
- Changing database schemas, core domain models, or cross-module interfaces.
- Advancing from Spec to Planning, or from Planning to Implementation.

### Never Do:
- Write code for unapproved or undecided architecture.
- Silently assume or guess developer intent on underspecified requirements.
- Overwrite or delete unchecked tasks in `tasks/plan.md` or `tasks/todo.md`.
- Introduce heavy external project management tooling (Jira, Linear, Notion).

---

## 5. Detailed Rules Index

- [Quality & Engineering Constraints](CONSTRAINTS.md)
- [Decision Authority Rule](.agents/rules/decision-authority.md)
- [Context Loading Checklist](.agents/rules/context-loading.md)
- [Documentation Lifecycle Rule](.agents/rules/documentation-lifecycle.md)
- [Architecture Decisions Log](docs/decisions/)
