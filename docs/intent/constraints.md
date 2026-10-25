# Statement of Intent: Constraints & Quality Bar

> **Topic:** Quality Bar & Engineering Constraints  
> **Status:** Confirmed by Developer  
> **Date:** 2026-10-09  
> **Skill Ref:** `constraint-driven-development` + `interview-me`

---

## 1. Intent Summary

- **Outcome:** Establish the quality contract document `CONSTRAINTS.md` in the repository root and update `AGENTS.md` to mandate strict adherence by all AI coding agents, prohibiting silent lowering of technical standards.
- **User:** Solo Developer (protected against regressions: eliminating the need to manually audit every AI-generated line while guaranteeing clean, fully typed code, zero leaked secrets, and strict 6-module architecture boundaries).
- **Why now:** Transitioning from Phase 0 (Capability Map) to Phase 1 (authoring specs and implementing foundational modules `api-contract` & `backend-engine`).
- **Success Criteria:** `CONSTRAINTS.md` codified with concrete quantitative thresholds (**Sane Defaults**):
  - **Floor:** Zero suppression comments (`@ts-ignore`, `eslint-disable`, `# noqa`), zero empty stubs (`throw new Error`, empty `catch {}`), zero skipped/deleted tests, zero hardcoded secrets or API tokens.
  - **Enforced:** 0 static type errors (Pydantic, mypy, strict TypeScript), 0 high+ security vulnerabilities, 0 module boundary violations, $\ge 80\%$ test coverage on modified lines.
  - **Action:** **Block** (immediately halt agent actions and mandate instant remediation upon violation).
  - **Time Budget:** $\le 5$s per file edit (`check:fast`), $\le 90$s upon completing a task (`check:task`).
- **Constraints:** Every metric must be enforced by automated tooling; never weaken constraint files to make builds pass.
- **Out of scope:** Hard blocking on inference latency budgets or GPU VRAM footprint during initial setup (monitored in "Measured, not yet enforced" status).
