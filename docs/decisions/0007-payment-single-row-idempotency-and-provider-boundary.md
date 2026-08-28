# 0007. Payment is a single idempotent row per checkout; the provider boundary stays a two-method protocol

## Status

Accepted

## Context

Milestone 5 adds the first point where the system actually moves money:
a checkout that is `ALLOW` or has a valid `CheckoutAuthorization`
(`docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`) can be
charged through Razorpay Test Mode. Two design questions aren't settled by
that ADR or by `CLAUDE.md`'s determinism boundary alone:

1. What does a payment *attempt* look like as a durable record — one row
   per checkout, one row per attempt, or something else — given that a
   provider order can legitimately fail and need retrying, but a checkout
   must never end up with two live payment attempts or two successful
   payments?
2. How much should the payment domain know about Razorpay specifically, and
   how much should `app.commerce.payment.service` trust the provider's own
   SDK versus verifying the one security-critical fact (the payment
   signature) itself?

## Decision

**`Payment` is one row per checkout (`UniqueConstraint("checkout_id")`),
updated in place across retries rather than inserting a new row per
attempt.** This is the same "single mutable row" pattern
`MerchantPolicy` already uses, applied to a provider-order lifecycle
instead of a policy value: a failed attempt (`status = failed`) can be
retried by `initiate_payment`, which creates a new Razorpay order and
overwrites `provider_order_id`/`amount_minor_units`/`currency` on the
existing row rather than creating a second `Payment`. This makes "at most
one successful payment per checkout" a database constraint, not just an
application check, and it means a checkout can never accumulate multiple
live attempts. A full per-attempt ledger (every provider request/response,
every retry as its own row) is deliberately deferred — that's M6's
transaction/audit concern, not M5's.

**Eligibility is re-derived from scratch at both `initiate_payment` and
`confirm_payment`, never cached between them.** This mirrors
`authorize_checkout`'s own re-check of live checkout state between
evaluation and approval. Concretely: `initiate_payment` never calls the
provider until the checkout is loaded fresh and its policy
decision/authorization checked; `confirm_payment` repeats both checks
immediately before verifying the signature, and if either has stopped
holding (checkout expired between initiation and confirmation, say), the
`Payment` is marked `failed` and the provider's `verify_payment` is never
even called for that attempt.

**Signature verification is implemented directly with the stdlib
(`hmac`/`hashlib`) against Razorpay's documented formula
(`HMAC-SHA256("{order_id}|{payment_id}", key_secret)`), not via
`razorpay.Client().utility.verify_payment_signature`.** The SDK's own
`errors` module (`BadRequestError`, `GatewayError`, `ServerError`,
`SignatureVerificationError`) shares no common base class besides
`Exception`, so there's no single exception type to catch generically;
implementing the (simple, fully documented) HMAC check ourselves keeps the
one genuinely security-critical operation in this codebase fully
unit-testable with zero network access and no dependency on the SDK's
internal error hierarchy. `create_order` still goes through the official
SDK, since request/response mapping there is not security-critical and the
SDK saves us from hand-rolling HTTP/auth.

**`PaymentProvider` (`app.commerce.payment.provider`) stays exactly two
methods — `create_order`/`verify_payment` — with no refund, capture,
subscription, or webhook methods.** Those aren't needed until M6 at the
earliest; adding them speculatively would just be unused surface area.

## Consequences

- A checkout's payment history is legible as "the current attempt," not a
  timeline — that's the right amount of detail for M5's synchronous
  create-order → Checkout.js → confirm flow, and is simpler to reason about
  than a ledger. If M6 needs a full attempt history for audit purposes, it
  is layered on top (e.g. an append-only `payment_attempts` table) rather
  than changing what `Payment` means.
- The determinism boundary holds the same way it does for policy: nothing
  in `app.commerce.payment` ever asks an LLM whether to pay, and nothing
  trusts a caller-supplied amount/currency — both always come from
  `Checkout.total_minor_units`/`currency`. There is still no payment tool
  in `app.agents` (see `docs/decisions/0004-agent-tool-contract.md`); this
  remains enforced by omission, backed by a regression test
  (`tests/agents/test_architecture.py::test_no_payment_tool_is_declared`).
- Retrying a failed payment reuses the same `idempotency_key`
  (`str(checkout_id)`) and the same row; a second provider order is only
  ever created after the first attempt has actually failed, never as a
  reaction to a client simply calling the initiate endpoint twice while an
  order is still live.
