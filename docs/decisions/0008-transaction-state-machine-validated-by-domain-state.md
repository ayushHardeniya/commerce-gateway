# 0008. The transaction state machine validates transitions against live domain state, not caller assertions

## Status

Accepted

## Context

Milestone 6A introduces `Transaction`, a durable, business-level record of
one commerce attempt as it moves across discovery, cart, checkout, policy,
and payment. Checkout, policy, and payment already each have their own
authoritative state (`Checkout.status`/`effective_status`, `PolicyDecision`,
`CheckoutAuthorization`, `Payment.status`) — `app.commerce.transaction` adds
a higher-level view across all of them, not a fourth copy of any of it.

Two things had to be decided before writing the state machine:

1. **What stops a transition from being a bare, trusted write?** A naive
   `PATCH /transactions/{id} {state: "payment_success"}` would let *any*
   caller — including, eventually, an AI buyer or anything acting on its
   behalf — simply assert that a payment succeeded. `CLAUDE.md`'s
   determinism boundary explicitly calls out "transaction state transitions"
   and "payment success must not be inferred from an LLM response" as hard
   constraints; a bare-write API satisfies neither.
2. **How much of the checkout/policy/payment flow does a `Transaction` need
   to duplicate to answer that?** `Payment` and `PolicyDecision` already
   solved a similar problem — re-derive eligibility from the real records
   at the moment it matters, never cache or trust it — see
   `docs/decisions/0006-policy-snapshot-and-explicit-authorization.md` and
   `app.commerce.payment.service._ensure_policy_eligible`. The transaction
   layer should reuse that pattern, not reinvent it.

## Decision

**The state machine is a fixed table of `(from_state, to_state)` edges, each
with a guard function.** `transition_transaction` looks up the edge for the
transaction's current state and the caller's requested `to_state`; if no
such edge exists, the transition is rejected outright
(`invalid_transaction_transition`) — this alone makes the graph shape
deterministic and enforced (no skipping `cart_created`, no leaving a
terminal state).

**For edges backed by a real domain fact, the guard re-reads that fact from
its owning table before accepting the transition — it never accepts a
caller's claim about it.** Concretely:

- `policy_pending → authorized` re-reads the checkout's `PolicyDecision`
  (and, if `require_authorization`, its `CheckoutAuthorization`) via
  `app.commerce.policy.repository` — the same ALLOW-or-valid-authorization
  check `payment.service._ensure_policy_eligible` already performs.
- `policy_pending → policy_denied` requires the recorded decision to
  actually be `deny`.
- `authorized → payment_pending` requires a `Payment` row in `created`
  status to already exist for the checkout.
- `payment_pending → payment_success` / `→ payment_failed` require
  `Payment.status` to actually be `success` / `failed`.
- `checkout_created`/`policy_pending`/`authorized → checkout_expired`
  require `Checkout.effective_status == "expired"`.
- `payment_success → order_confirmed` requires `Checkout.status ==
  "completed"` (set by `payment.service.confirm_payment` on a verified
  signature).

An edge with no real fact to check (e.g. `checkout_created → policy_pending`,
which only marks intent to begin evaluation) has no guard beyond the graph
itself — not every edge needs one, only the ones a caller could otherwise
falsify.

**`Transaction` references `cart_id`/`checkout_id`, both nullable; it stores
no copy of cart, checkout, policy, or payment data.** A transaction can
exist before either reference is known (`discovered`), and every guard
above reads the referenced table directly rather than a cached field —
so a `Transaction` can never disagree with the record it's describing.

**No `Tool` in `app.agents` reaches `create_transaction` or
`transition_transaction`.** The only path to either is
`app.commerce.transaction.router` (HTTP), the same enforced-by-omission
pattern `docs/decisions/0004-agent-tool-contract.md` established for
`authorize_checkout` and payment initiation/confirmation — backed by
`tests/agents/test_architecture.py::test_no_transaction_tool_is_declared`.

**Checkout-flow integration is by reference, not by modifying
`app.commerce.checkout`.** `create_transaction(checkout_id=...)` starts a
transaction directly at `checkout_created` for an already-existing
checkout, deriving `cart_id` from it. No change to `app.commerce.checkout`
was necessary for this — a `Transaction` only ever depends on `Checkout`,
never the reverse, the same dependency direction `app.commerce.payment`
already has toward `app.commerce.checkout`/`app.commerce.policy`.

**One mutable row per transaction, updated in place — not a per-transition
history table.** Same pattern as `Payment`/`MerchantPolicy`. A full,
queryable audit trail of every transition (who/when/why, not just the
current state) is explicitly out of scope for M6A; see the "Deferred to
M6B" list in `CLAUDE.md`.

## Consequences

- A transition can fail for two distinctly different reasons that both
  surface as the same `invalid_transaction_transition` (409): the edge
  doesn't exist in the graph at all, or it exists but the live record it's
  guarded by doesn't currently support it. Both mean "you can't do that
  right now" from the caller's point of view, so collapsing them keeps the
  error surface small; the `message` text distinguishes the two for anyone
  reading it.
- Because a guard re-reads live state, a transition's success can depend on
  what happened in `app.commerce.checkout`/`policy`/`payment` since the
  transaction was last touched — this is intentional (the same "never
  trust a cached fact" principle payment eligibility already relies on),
  but it does mean transitioning a `Transaction` is not just a local state
  update; the caller must have already driven the underlying checkout/
  policy/payment step (e.g. actually initiate a payment) before the
  transaction can follow.
- `payment_failed → payment_pending` (retry) requires a *new* `Payment` row
  in `created` status to already exist — i.e. the caller must call
  `payment.service.initiate_payment` again first. The transaction layer
  does not initiate payment retries itself.
