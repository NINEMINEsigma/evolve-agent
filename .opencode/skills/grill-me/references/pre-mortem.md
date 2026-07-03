# Pre-Mortem Analysis Guide

A pre-mortem assumes the plan has been implemented and failed catastrophically. Working backward from failure surfaces risks that forward planning misses.

## When to Run

Run after core decisions are resolved but before concluding the session. Do not skip this step for medium/deep sessions.

## Procedure

### Step 1: Set the scene

> "It is six months from now. The system is in production and has failed badly. What happened?"

### Step 2: Generate failure modes

Invent specific, plausible failure scenarios tied to decisions made in this session:

| Failure mode | Likely cause | Early warning signal | Prevention |
|-------------|--------------|---------------------|------------|
| <scenario> | <which decision went wrong> | <what metric/alert catches it> | <what would have prevented it> |

Target 3-5 failure modes. Prioritize:
1. Cascade failures (one bad decision breaks multiple subsystems)
2. Silent failures (the system appears to work but produces wrong results)
3. Scaling failures (works at small scale, breaks at large)

### Step 3: Identify the weakest decision

Ask: "If only one decision from this session could be wrong, which would cause the most damage?"

Mark that decision as [RISKY] in the decision log and add a specific monitoring/mitigation plan.

### Step 4: Extract risk register entries

Every plausible failure mode becomes an entry in the decision log's Risk Register with:
- **Severity**: high (system down), medium (degraded), low (inconvenience)
- **Trigger condition**: when to escalate from monitoring to action
- **Owner**: who is responsible for watching this risk

## Example

> **Failure mode**: "Orders are double-charged under load."
> **Likely cause**: "We chose optimistic concurrency for the payment gateway (D3) but didn't implement idempotency keys."
> **Early warning**: "Duplicate charge rate > 0.01%."
> **Prevention**: "Add idempotency keys before going live; monitor charge uniqueness."

## Rules

- Do not accept vague risks like "performance issues" — demand specifics
- Tie every risk back to a specific decision from this session
- If a risk has no mitigation strategy, the decision is not ready to be marked [RESOLVED]
- The pre-mortem is not about pessimism — it's about making the plan robust enough to survive reality
