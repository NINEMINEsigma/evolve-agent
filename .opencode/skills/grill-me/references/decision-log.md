# Decision Log Format

The decision log is the durable artifact produced by a `grill-me-pro` session. It captures every resolved decision, its context, and its downstream implications in a format that downstream skills (`to-prd`, `to-issues`) can consume directly.

## File Location

Save as `decision-log.md` in the project's `docs/` directory (or project root if no `docs/` exists).

## Template

```markdown
# Decision Log — <Session Title>

**Date**: YYYY-MM-DD
**Topic**: <brief description of what was grilled>
**Depth**: light | medium | deep
**Status**: complete | partial (note which branches remain open)

---

## Decisions

### D1: <Decision Title>

**Status**: [RESOLVED] | [DEFERRED] | [RISKY]
**Question**: <the exact question that was asked>
**Answer**: <the agreed-upon answer>
**Trade-off accepted**: <what cost/risk/constraint the user accepted>
**Local evidence**: <what the codebase said, or "none found">
**External evidence**: <engineering precedent consulted, or "none consulted">
**Terms defined**: <any glossary terms resolved by this decision>
**Downstream impact**: <which later decisions depend on this one>

---

## Risk Register

| ID | Risk | Severity | Mitigation | Owner |
|----|------|----------|------------|-------|
| R1 | <description> | high/medium/low | <strategy> | <who watches> |

---

## Terminology Updates

| Term | Definition | Alias/avoid |
|------|------------|-------------|
| <term> | <one-sentence definition> | _Avoid_: <old terms> |

---

## ADRs Created

- `docs/adr/XXXX-<slug>.md` — <title>

---

## Open Questions (Deferred)

- <question> — deferred until <trigger condition>

---

## Handoff Notes

Recommended next step: `to-prd` | `to-issues` | `grill-me-pro --light` | none
Key context for implementer: <what the next skill needs to know>
```

## Rules

- Every decision gets a stable ID (`D1`, `D2`, ...) for downstream referencing
- Preserve the exact question and answer, not a summary — summaries lose nuance
- Record the trade-off explicitly — this is the most important field
- Note which decisions have downstream dependencies — this creates the tree structure
- Risks are separate from decisions — a decision can be correct and still risky
- Deferred decisions must have a trigger condition, not just "later"
