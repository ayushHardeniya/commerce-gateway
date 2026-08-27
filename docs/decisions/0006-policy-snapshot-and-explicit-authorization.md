# 0006. Policy decisions snapshot their governing policy; authorization is an explicit, one-time, re-checked record

## Status

Accepted

## Context

Milestone 4 introduces the first point where the system decides whether a
checkout may proceed *autonomously* or needs a human in the loop, and the
mechanism by which a human grants that approval. `CLAUDE.md`'s determinism
boundary already rules out an LLM making that call; this decision is about
the two things that boundary doesn't settle by itself:

1. A merchant's policy (their autonomous spending limit) is naturally
   mutable — they can raise or lower it whenever they like. But a policy
   *decision* made against a checkout is meant to be a stable, explainable
   fact about a specific moment. If a merchant edits their policy an hour
   after a decision was made, does that retroactively change what the
   earlier decision meant? It must not — a future audit trail (out of scope
   here) needs to answer "what did policy actually say about checkout X"
   without also needing "...and what was the policy row's value at that
   exact timestamp," which a naive foreign key to a mutable row can't answer
   once the row has since changed.
2. Authorization is the one place in this milestone where a human, not code,
   makes a judgment call. What has to be true for that approval to count?
   It needs to be impossible for it to attach to the wrong checkout, the
   wrong amount, or a checkout that has since changed underneath it —
   including changes that happen *between* evaluation and authorization,
   not just before.

## Decision

**`PolicyDecision` copies the exact policy values it was computed against
onto itself** (`policy_version`, `autonomous_limit_minor_units`,
`policy_currency`), rather than only holding a foreign key to
`MerchantPolicy`. `MerchantPolicy` itself stays a single mutable row per
merchant (`version` increments on every update) — there is no
`policy_versions` history table. This is deliberately the smallest
mechanism that satisfies the invariant: a decision's meaning is fixed the
moment it's created, and reading it back later never requires reasoning
about what the live `MerchantPolicy` row looked like at some point in the
past. `policy_version = 0` is reserved to mean "no explicit policy existed;
the safe default was applied" (see below) — never a version a real
`MerchantPolicy` row can have.

**`evaluate_checkout` is idempotent, not re-run.** A checkout gets exactly
one `PolicyDecision`, computed once; every later call (including a merchant
changing their policy in between) returns the same row unchanged. This is
what actually makes the snapshot meaningful: without it, "snapshot the
policy" and "re-run evaluation on demand" would be two features quietly
fighting each other.

**A merchant with no explicit `MerchantPolicy` gets `autonomous_limit = 0`,
not unrestricted spending.** Every nonzero checkout requires human
authorization until the merchant explicitly configures a higher limit. This
is the one safe direction to fail in for money-moving decisions.

**`CheckoutAuthorization` is the sole record of human approval, and its
existence for a checkout *is* the AUTHORIZED state** — there is no separate
status enum to drift out of sync with it. Authorization is granted only
through `app.commerce.policy.service.authorize_checkout`, reachable solely
via `app.commerce.policy.router` (HTTP), never via `app.agents` — enforced
by omission, the same pattern `docs/decisions/0004-agent-tool-contract.md`
established for cart/checkout tools. Granting it requires all of:

- a `PolicyDecision` already exists for the checkout (evaluate-then-authorize,
  never implicit),
- no `CheckoutAuthorization` already exists for it (one-time, via a unique
  constraint on `checkout_id`),
- the decision is `require_authorization` — not `allow` (nothing to
  authorize) and not `deny` (never authorizable),
- the checkout is currently `active` (re-checked fresh, not read from the
  decision snapshot — expiry is a derived, time-based fact that can become
  true *after* the decision was made),
- the caller's stated `amount_minor_units`/`currency` match the checkout's
  *current* authoritative total, **and** the checkout's current total still
  matches what the `PolicyDecision` itself recorded.

That last double-check is intentional belt-and-suspenders: the M3 checkout
model already freezes `total_minor_units`/`currency` at creation with no
update path, so today these two comparisons can never actually disagree —
but the invariant ("authorization must be bound to *this* checkout's *this*
amount") is meant to hold even if that assumption about `Checkout`
immutability changes later, not just today.

## Consequences

- A `PolicyDecision`, once made, is a permanent, self-contained explanation
  of a checkout's policy outcome — a future audit trail can display it
  without joining against `MerchantPolicy`'s current state, and a merchant
  tightening or loosening their limit can never rewrite the meaning of a
  decision already made.
- `MerchantPolicy` staying a single mutable row (rather than a history
  table) is a real simplification, and it's safe specifically *because*
  `PolicyDecision` snapshots what it needs — there would be no way to
  recover "what limit applied to decision X" from `MerchantPolicy` alone
  once it's been updated since.
- Authorization is checked against live checkout state at the moment of
  authorization, not only against the decision snapshot — closing the
  window between "policy was evaluated" and "a human clicks approve."
- This does not build a policy rules engine (no rule composition, no
  per-category or per-time-window limits) or a general authorization/identity
  system (no auth, no notion of *which* human approved) — both explicitly
  out of scope for this milestone. The one-time, checkout-scoped
  `CheckoutAuthorization` record is sufficient to establish "a human approved
  this checkout, for this amount, under this decision" without either.
- No payment happens anywhere in this milestone. `AUTHORIZED` is a distinct,
  explicit state (`CheckoutAuthorization` existing) from any future
  `PAYMENT_SUCCESS` — the two are not conflated even at the schema level.
