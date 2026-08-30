import type { TransactionState } from "./api";

/**
 * Which states the backend never leaves — mirrors
 * `app.commerce.transaction.service.TERMINAL_STATES` (also documented in
 * `ARCHITECTURE.md`'s transaction module section) purely so the polling
 * loop below knows when to stop. This is a classification of state
 * *names*, not the transition graph — it says nothing about which edges
 * are valid or what a guard requires, so it isn't a copy of the FSM; only
 * `app.commerce.transaction.service._TRANSITIONS` decides that, and this
 * frontend never touches it. If the backend's terminal set ever changes,
 * the worst case here is over- or under-polling briefly, never an invalid
 * or misleading transition.
 *
 * `payment_failed` is deliberately excluded: it has a real outgoing edge
 * (a retried payment can move it back to `payment_pending`), so it's worth
 * continuing to poll in case that happens elsewhere (another tab, another
 * operator).
 */
const TERMINAL_TRANSACTION_STATES: ReadonlySet<TransactionState> = new Set([
  "order_confirmed",
  "policy_denied",
  "checkout_expired",
  "cancelled",
  "failed",
]);

export function isTerminalTransactionState(state: TransactionState): boolean {
  return TERMINAL_TRANSACTION_STATES.has(state);
}
