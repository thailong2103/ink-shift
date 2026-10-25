# Rule: Agent Session Context Loading Checklist

> **Applies to:** All AI coding agents interacting with the InkShift repository.  
> **Purpose:** Ensure deterministic, zero-drift context loading at the beginning of each session.  

---

## 1. Startup Inspection Checklist

Every agent session MUST execute this checklist sequentially before taking action:

```markdown
- [ ] 1. Read AGENTS.md (Root context rules and authority boundary)
- [ ] 2. Read docs/PROJECT_STATE.md (Current timeline, tech stack, module map, active work)
- [ ] 3. Read tasks/todo.md (Pending and in-flight tasks)
- [ ] 4. Check git status (Ensure working tree is clean)
```

---

## 2. Session Context Verification Heuristic

Before answering the developer's first request or starting a task, verify mentally:
- Do I know what week/milestone we are in? (From `PROJECT_STATE.md`)
- Do I know what module is currently being built?
- Do I know what technologies are approved and forbidden?
- If the developer asks me to write code, has the spec in `docs/specs/` been marked `Status: Approved`?

If any of these answers are unclear, the agent must check the relevant document in `docs/` or ask the developer for clarification rather than making assumptions.

---

## 3. End-of-Session / Task Completion Routine

When completing a task from `tasks/todo.md`:
1. Check off the completed item in [tasks/todo.md](../../tasks/todo.md).
2. If the task introduced architectural changes or completed a milestone, update [docs/PROJECT_STATE.md](../../docs/PROJECT_STATE.md).
3. Ensure all tests or verification steps described in the task pass.
4. Prepare clean, atomic Git commit messages adhering to standard conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).
