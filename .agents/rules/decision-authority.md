# Rule: Decision Authority and Boundary Enforcement

> **Applies to:** All AI coding agents interacting with the InkShift repository.  
> **Source Intent:** [docs/intent/sdlc-governance.md](../../docs/intent/sdlc-governance.md)  
> **Core Tenet:** The agent proposes; the human decides. No exceptions.  

---

## 1. Authority Boundaries

### What the Human Owns (Sole Authority):
1. **Architecture & Design:** Selecting application frameworks, architectural patterns, state architectures, and domain boundaries.
2. **Dependencies & Tooling:** Approving the addition, upgrade, or replacement of any third-party library, package, or tool.
3. **Data Schemas & Contracts:** Approving database schemas, migration scripts, and public API shapes.
4. **Scope & Priorities:** Deciding what features enter the 4-week roadmap, what gets cut, and what order modules are built.

### What the Agent Owns (Advisory & Execution):
1. **Trade-off Analysis:** Researching options and providing objective comparison matrices (Pros, Cons, Constraints, Performance implications).
2. **Quality Advocacy:** Pushing back with reasoned technical arguments if a direction violates performance, accessibility, security, or project goals.
3. **Implementation within Approved Specs:** Writing code, unit tests, and documentation strictly within the boundaries of approved specifications (`docs/specs/SPEC-*.md`).

---

## 2. Hard Stop Triggers

The agent MUST stop execution and prompt the human developer in the following scenarios:

1. **New Package Requirement:** An implementation step requires installing an npm package or external tool.  
   *Action:* Stop, present the package name, version, alternative lightweight approaches, and wait for human confirmation.
2. **Ambiguous Requirements:** A specification or user prompt does not specify error behavior, layout structure, or business logic.  
   *Action:* Stop, list assumptions explicitly under `ASSUMPTIONS I'M MAKING:`, and request confirmation.
3. **Architectural Fork:** Multiple viable patterns exist (e.g., Redux vs. Zustand, Server Actions vs. API routes).  
   *Action:* Stop, prepare an options comparison table, provide an agent recommendation, and wait for the human decision.

---

## 3. ADR Creation Requirement

An Architecture Decision Record (ADR) in `docs/decisions/` is mandatory whenever:
- A new technology or core library is added to the tech stack.
- A foundational pattern is adopted (e.g., repository pattern, error handling strategy).
- A significant architectural migration or refactoring takes place.

Every ADR must follow [docs/decisions/template.md](../../docs/decisions/template.md) and be marked with sequential numbering (`ADR-001`, `ADR-002`, ...).
