---
name: grill-me-pro
description: Interview the user about any plan one question at a time until shared understanding. Use when user wants to stress-test a plan or mentions 'grill me'.
---

# Grill Me Pro — Super-Enhanced Interrogation Skill

> **Philosophy**: The quality of implementation is bounded by the clarity of intent. This skill exists to make intent explicit before a single line of code is written.

Conduct a relentless, one-question-at-a-time interrogation session that walks the user down every branch of their design tree, resolving dependencies between decisions one-by-one until shared understanding is reached.

**Core operating principle**: For each unresolved decision, inspect the local codebase first, calibrate against external engineering evidence, provide a recommended answer with visible trade-offs, then ask exactly one precise question and wait for the user's response before continuing.

---

## Session Lifecycle

### 1. Initialize

Begin every session by:
- Reading `CONTEXT.md` (if exists) and any existing ADRs to understand the project's domain language
- Reading the user's initial plan or description
- Computing a rough decision-tree outline: identify the major decision branches and their dependencies
- Stating the session's interrogation scope and estimated depth (light: 3-7 questions, medium: 8-15, deep: 16+)

### 2. Interrogate (main loop)

For each unresolved decision in dependency order:

```
Decision: <what we are deciding>

Local findings:
- <relevant code/config/schemas, or "not answered locally">

External calibration:
- <engineering precedent with sources, or "no strong precedent found">

Recommendation: <copy/adapt/reject + why>
Trade-off you'd accept: <the cost, risk, or future constraint>

Question: <one precise question>
```

**Rules for the loop:**
- Ask **one question at a time**. Batching kills the grilling rhythm and lets the user dodge specifics.
- Provide a **recommended answer** with every question. Neutrality is not grilling.
- Walk the **design tree in dependency order**; resolve upstream choices before their downstream consequences.
- **Explore the codebase instead of asking** when the answer is inspectable. Prefer `rg` and targeted file reads over broad exploration.
- Do not accept "TBD" or vague answers — push until concrete.
- Conduct the entire session in the **same language the user writes in** (default: Chinese). Domain terminology can stay in English where it serves as canonical terms.

### 3. Domain Awareness & Terminology

During the session, maintain a live glossary:
- When the user uses a term that conflicts with `CONTEXT.md`, call it out immediately
- When terminology is fuzzy, force precision: propose a canonical term, flag overloaded terms, split terms hiding multiple concepts
- Update `CONTEXT.md` inline as terms resolve — do not batch
- When a decision meets all three criteria (hard to reverse, surprising without context, result of real trade-off), offer to create an ADR

### 4. Scenario Pressure Testing

After resolving core decisions, invent concrete scenarios that probe edge cases:
- Partial failure and retries
- Migration and rollback
- Concurrent updates
- Deleted/archived/expired entities
- Permission and ownership boundaries
- Degraded dependencies
- Unexpected scale changes
- Future feature pressure

Tie each scenario back to the decisions under discussion to make hidden costs visible.

### 5. Pre-Mortem Analysis

Before concluding, run a pre-mortem: assume the plan has been implemented and failed. Ask:
- "What is the most likely reason this design fails in production?"
- "Which decision, if wrong, causes the worst cascade failure?"
- "What early warning signal would tell us a decision was wrong?"

Record identified risks in the decision log.

### 6. Conclude & Output

When the decision tree is fully resolved (all branches marked [RESOLVED]):

1. Present a **decision summary** showing:
   - All resolved decisions with accepted trade-offs
   - Open risks and their mitigation strategies
   - Terms added or updated in the glossary
   - ADRs created or recommended

2. Produce a **decision log artifact** (`decision-log.md`) following the format in [references/decision-log.md](references/decision-log.md).

3. Offer handoff to downstream skills (see [references/downstream-skills.md](references/downstream-skills.md) for concepts):
   - `to-prd` (planned): convert resolved decisions into a PRD
   - `to-issues` (planned): break decisions into implementable issues
   - `grill-me-pro --light`: run a lighter follow-up session

4. Mark the session complete.

---

## Decision Tracking Protocol

Track each decision's state inline using status markers:

```
[OPEN] Decision has been identified but not yet resolved
[RESOLVED] Decision has been agreed upon with explicit trade-off
[DEFERRED] Decision intentionally postponed with trigger condition
[RISKY] Decision accepted with known risk, requires monitoring
```

At any point, the user can ask for a **progress snapshot** — show the current decision tree with status markers and open frontier.

---

## Evidence Hierarchy

When calibrating decisions against external evidence, use this priority order:

1. Production-grade open-source codebases with similar constraints
2. Official framework, language, database, or cloud-provider documentation
3. Research papers, RFCs, standards, or formal design notes
4. Engineering blogs, conference talks, incident writeups from credible teams
5. Community consensus signals (forums, GitHub issues, HN, Reddit)

When citing, explain whether the outside example is actually comparable to the user's situation. Avoid treating popularity as proof.

---

## Documentation Capture Rules

Do not make documentation the center of the session. Only capture when:
- The user explicitly requests it
- A decision has crystallized and there's an obvious durable place

Follow existing project conventions. If no convention exists, ask before creating new files.

Create ADRs sparingly — only when all three are true:
1. Hard to reverse
2. Surprising without context
3. Result of a real trade-off

See:
- [references/decision-log.md](references/decision-log.md) — decision log format
- [references/pre-mortem.md](references/pre-mortem.md) — pre-mortem methodology
- [references/downstream-skills.md](references/downstream-skills.md) — downstream skill concepts (planned)
- [references/triggers.md](references/triggers.md) — trigger keywords for agent platforms
