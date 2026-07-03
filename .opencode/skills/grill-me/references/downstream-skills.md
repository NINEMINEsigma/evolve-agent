# Downstream Skills — Concept Specification

This document defines the planned downstream skills that consume `grill-me-pro`'s output. These skills are **not yet implemented**; they are specified here as a contract for future development.

## Overview

```
grill-me-pro → decision-log.md → [to-prd | to-issues | grill-me-pro --light]
```

The decision log is the universal handoff artifact. Each downstream skill reads it and produces a different output format.

---

## to-prd (Planned)

**Purpose**: Convert a resolved decision log into a Product Requirements Document.

**Input**: `decision-log.md` with all critical decisions marked [RESOLVED] or [RISKY].

**Output**: `prd.md` following a standard template.

**Process**:
1. Read decision-log.md and extract all decisions
2. Group decisions by functional area (e.g., auth, data model, API)
3. For each group, write:
   - **Overview**: what this area does and why
   - **Requirements**: functional requirements derived from decisions
   - **Decisions**: the specific choices made, with trade-offs
   - **Open questions**: any [DEFERRED] decisions that affect this area
   - **Risks**: relevant entries from the risk register
4. Include terminology glossary from the decision log
5. Add "Out of Scope" section listing anything explicitly deferred

**Trigger**: User says "convert this to PRD" or decision log handoff note recommends `to-prd`.

---

## to-issues (Planned)

**Purpose**: Break a resolved decision log into implementable GitHub/GitLab issues.

**Input**: `decision-log.md` with all critical decisions marked [RESOLVED] or [RISKY].

**Output**: A set of issue files or direct API-created issues.

**Process**:
1. Read decision-log.md and build the decision tree
2. Identify leaf decisions (no downstream dependencies) — these become implementation tasks
3. Group related leaf decisions into epics
4. For each issue:
   - Title: action-oriented (e.g., "Implement idempotency keys for PaymentIntent")
   - Description: link to the parent decision, include trade-off context
   - Labels: derived from decision area and risk level
   - Dependencies: reference upstream decisions that must be resolved first
5. Create an "Implementation order" section listing issues in dependency order

**Trigger**: User says "break this into issues" or decision log handoff note recommends `to-issues`.

---

## grill-me-pro --light

**Purpose**: Run a shorter follow-up session on a subset of decisions.

**Input**: Existing `decision-log.md` with some [OPEN] or [DEFERRED] decisions.

**Process**:
1. Read the existing decision log
2. Identify the open frontier ([OPEN] decisions and their dependencies)
3. Run a condensed grilling session (light depth: 3-7 questions)
4. Update the same decision-log.md in-place

**Trigger**: User says "follow up on the deferred decisions" or "grill me on the remaining open questions".

---

## Decision Log as Universal Interface

The key design principle: the decision log is the **single source of truth** between skills.

| Skill | Reads | Produces |
|-------|-------|----------|
| grill-me-pro | User input, codebase, external evidence | decision-log.md |
| to-prd | decision-log.md | prd.md |
| to-issues | decision-log.md | issues/ |
| grill-me-pro --light | decision-log.md | Updated decision-log.md |

No skill talks directly to another skill. All communication happens through the decision log. This makes each skill independently testable and replaceable.
