# Decision Log — Payment Gateway Integration

**Date**: 2026-07-03
**Topic**: Design payment flow for e-commerce platform
**Depth**: medium
**Status**: complete

---

## Decisions

### D1: Payment Provider Selection

**Status**: [RESOLVED]
**Question**: Which payment provider should we use for the initial launch?
**Answer**: Stripe for card payments, with PayPal as fallback
**Trade-off accepted**: Higher per-transaction fees (2.9% + 30¢) in exchange for faster integration and better developer experience
**Local evidence**: No existing payment code found
**External evidence**: Stripe is the de facto standard for startups; PayPal covers users who prefer not to enter card details
**Terms defined**: PaymentIntent (Stripe's unified payment object), Webhook endpoint
**Downstream impact**: D2 (webhook handling), D3 (idempotency strategy)

---

### D2: Webhook Handling Strategy

**Status**: [RESOLVED]
**Question**: How should we handle Stripe webhooks for async payment events?
**Answer**: Queue webhooks to Redis, process asynchronously with retry logic
**Trade-off accepted**: Adds Redis dependency and complexity; avoids blocking webhook responses and handles spikes
**Local evidence**: No webhook infrastructure exists
**External evidence**: Stripe recommends responding within 5 seconds; queuing is standard practice (Shopify, GitHub)
**Terms defined**: Webhook endpoint signature verification, idempotency key
**Downstream impact**: D3 (depends on D1 for PaymentIntent flow)

---

### D3: Idempotency and Duplicate Prevention

**Status**: [RISKY]
**Question**: How do we prevent double-charging if a user clicks "Pay" twice?
**Answer**: Use Stripe's idempotency keys on PaymentIntent creation, plus our own order-level deduplication
**Trade-off accepted**: Additional complexity in order state machine; potential edge cases with network partitions
**Local evidence**: Order state machine exists but no idempotency logic
**External evidence**: Stripe docs recommend idempotency keys; payment industry standard (PCI compliance)
**Terms defined**: Idempotency key, network partition, exactly-once processing
**Downstream impact**: None (leaf decision)

---

### D4: Refund Flow Design

**Status**: [DEFERRED]
**Question**: Should refunds be initiated by users (self-service) or admin-only?
**Answer**: Admin-only for MVP; self-service considered for v2
**Trade-off accepted**: Higher support burden initially; defers complex authorization and fraud prevention
**Local evidence**: Admin dashboard exists but no refund UI
**External evidence**: Most e-commerce starts admin-only; self-service requires abuse prevention
**Terms defined**: Refund window (30 days), partial refund
**Downstream impact**: None (deferred until v2)

---

## Risk Register

| ID | Risk | Severity | Mitigation | Owner |
|----|------|----------|------------|-------|
| R1 | Double-charging under load | high | Idempotency keys + monitoring | Backend team |
| R2 | Webhook delivery failures | medium | Retry queue + dead letter | Backend team |
| R3 | Refund abuse (v2) | medium | Rate limiting + audit log | Product team |

---

## Terminology Updates

| Term | Definition | Alias/avoid |
|------|------------|-------------|
| PaymentIntent | Stripe's unified payment object representing a single payment attempt | _Avoid_: charge, transaction |
| Idempotency key | Unique key ensuring duplicate requests produce the same result | _Avoid_: dedup key |
| Webhook endpoint | HTTPS URL receiving async event notifications from Stripe | _Avoid_: callback URL |

---

## ADRs Created

- `docs/adr/0001-stripe-over-paypal.md` — Choosing Stripe as primary payment provider

---

## Open Questions (Deferred)

- Self-service refund policy — deferred until v2 (trigger: monthly refund request volume > 100)
- Multi-currency support — deferred until international launch

---

## Handoff Notes

Recommended next step: `to-prd`
Key context for implementer: D3 is marked [RISKY] — ensure idempotency implementation has thorough test coverage before going live
