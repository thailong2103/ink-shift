# Intent: Project Governance & Agent Context System

> **Status:** Confirmed  
> **Date:** 2026-10-08  
> **Decision-maker:** Solo Developer (human)  
> **Confirmed via:** Interview-me skill session  

---

## What We Are Building

A lightweight, living documentation system inside the InkShift repository that serves two purposes simultaneously:

1. **Human dashboard** — The developer always knows: where the project is, what has been decided, what technology is in use, how completed parts interact, and what remains to be done.
2. **Agent context protocol** — Every AI coding agent session begins by reading these documents and gains full, accurate understanding of the current project state. No guessing. No re-asking. No drifting.

## The Core Problem This Solves

Three failure modes observed in human-agent collaboration:

| Failure Mode | What Happens | Cost |
|---|---|---|
| **Context loss between sessions** | Agent forgets what technology is used, how modules connect, what has been built. It duplicates code, introduces bugs, or contradicts existing architecture. | Rework, debugging, wasted sessions |
| **Autonomous decision-making** | Agent picks libraries, mechanisms, or patterns the human never approved. The system becomes over-complex or limited relative to the original goal. | Architecture drift, unwanted complexity |
| **Silent assumption-filling** | Agent encounters ambiguity and fills it in silently instead of asking. Decisions get baked into code before the human even knows a choice was made. | Loss of control, misaligned implementation |

## Decision Authority Model

The human-agent relationship follows a strict authority boundary:

### Human (Decision-Maker)
- Makes ALL design and architecture decisions
- Approves or rejects every technology choice, mechanism, and pattern
- Reviews and signs off on specs before implementation begins
- Can change direction at any time; the documentation updates to reflect the new truth

### Agent (Advisor + Executor)
- **CAN** propose alternatives, compare trade-offs, give opinions
- **CAN** push back on ideas that drift from or contradict stated goals
- **CAN** flag risks, suggest improvements, recommend against a decision
- **CANNOT** make technology, architecture, or design decisions autonomously
- **CANNOT** introduce new dependencies, patterns, or mechanisms without explicit human approval
- **MUST** ask when encountering ambiguity rather than guessing
- **MUST** read governance docs at session start to load full project context

### The Rule in One Sentence
> The agent proposes; the human decides. No exceptions.

## What Success Looks Like

When this system is working correctly:

- A new agent session starts → agent reads docs → knows exactly: tech stack, module interactions, completed tasks, pending decisions, constraints
- Agent encounters a choice (which library? which pattern? which approach?) → stops and presents options with trade-offs → waits for human decision
- Human can open the docs at any time and see: current project state, decision history, what's done, what's next
- No code gets written for undecided architecture. No decisions get buried in implementation.

## Constraints

- **Lightweight, not enterprise:** This is a solo 4-week project. The documentation system must be easy to maintain and fast to update. If it becomes overhead, it will be abandoned.
- **LLM-friendly format:** All docs written in English, structured markdown, with clear headers and explicit statements. Optimized for agent context loading.
- **Lives in the repo:** Everything is version-controlled alongside the code. No external tools (Jira, Linear, Notion).

## Explicitly Out of Scope

- Scrum ceremonies (sprint planning, daily standup, retrospective)
- External project management tools
- CI/CD automation or quality gates (for now)
- Formal review processes or approval workflows beyond human confirmation
- Multi-developer collaboration protocols

---

*This intent document is the foundation. Spec, directory structure, and implementation details are downstream and will be decided separately.*
