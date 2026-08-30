import { humanize } from "./format";

/**
 * A small lookup from a backend reason/failure code to a fuller sentence —
 * every entry here only restates what that exact code already means in
 * `app.commerce.policy.service`/`app.commerce.payment.service`/
 * `app.commerce.transaction.service` (their own docstrings and constants),
 * never a new fact the backend didn't already establish. Anything not
 * listed falls back to `humanize(code)` — this table doesn't need to be
 * exhaustive, and a code missing from it is never treated as an error.
 *
 * Source of each entry:
 * - policy reasons: `app.commerce.policy.service.REASON_*`
 * - payment failure codes: `app.commerce.errors` (`invalid_payment_signature`,
 *   `payment_provider_error`, `payment_provider_timeout`, `invalid_payment_state`)
 * - transaction-level: `checkout_expired` default in
 *   `app.commerce.transaction.service._guard_any_to_checkout_expired`
 */
const REASON_EXPLANATIONS: Record<string, string> = {
  within_autonomous_limit: "The checkout total was within the merchant's autonomous spending limit.",
  autonomous_limit_exceeded:
    "The checkout total exceeds the merchant's autonomous spending limit and requires human authorization before it can be paid.",
  checkout_expired: "The checkout expired before this step completed.",
  checkout_invalid: "The checkout was no longer active (completed or cancelled) when this was evaluated.",
  currency_mismatch: "The checkout's currency doesn't match the merchant's configured policy currency, so it was denied.",
  invalid_payment_signature:
    "The payment signature returned by the provider did not verify — the payment was rejected for safety.",
  invalid_payment_state: "The confirmation received didn't match the payment's current state.",
  payment_provider_error: "The payment provider rejected the request.",
  payment_provider_timeout: "The payment provider did not respond in time.",
  authorization_required: "This checkout requires explicit human authorization before payment.",
};

/** A fuller explanation for a backend-supplied reason/failure code, when one
 * is known — otherwise just the humanized code. Never fabricates a reason
 * the backend didn't supply; the raw `code` should still be shown alongside
 * this wherever it's used. */
export function explainReason(code: string): string {
  return REASON_EXPLANATIONS[code] ?? humanize(code);
}
