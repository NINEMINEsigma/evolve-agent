# Decision Log — Test Shuffled Fields

**Date**: 2026-07-03
**Topic**: Testing parser robustness
**Depth**: light
**Status**: complete

---

## Decisions

### D1: Field Order Test Alpha

**Answer**: We chose option A because it's simpler.
**Status**: [RESOLVED]
**Downstream impact**: D2 (next decision)
**Trade-off accepted**: Less flexibility for faster delivery
**Question**: Which option should we pick?

---

### D2: Field Order Test Beta

**Status**: [RISKY]
**Question**: How do we handle failure?
**Answer**: Retry with exponential backoff.
**Downstream impact**: None (leaf)

---

### D3: Missing Optional Fields

**Status**: [DEFERRED]
**Question**: What about future scaling?
**Answer**: We'll address this in Q3.

---
