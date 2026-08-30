/**
 * Typed client for `/api/transactions` — mirrors `app.commerce.transaction.schemas`.
 * The state machine itself (which transitions are valid, what a guard
 * requires) lives only on the backend
 * (`app.commerce.transaction.service`); this module just calls it and
 * returns whatever it decided. No state value is computed here.
 */

import { apiGet, apiPost, ApiError } from "./client";

export type TransactionState =
  | "discovered"
  | "cart_created"
  | "checkout_created"
  | "policy_pending"
  | "authorized"
  | "payment_pending"
  | "payment_success"
  | "order_confirmed"
  | "policy_denied"
  | "payment_failed"
  | "checkout_expired"
  | "cancelled"
  | "failed";

export type AuditActorType = "system" | "agent";

export type Transaction = {
  id: string;
  cart_id: string | null;
  checkout_id: string | null;
  state: TransactionState;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  id: string;
  sequence: number;
  transaction_id: string;
  from_state: TransactionState | null;
  to_state: TransactionState;
  actor_type: AuditActorType;
  actor_id: string | null;
  reason: string | null;
  event_metadata: Record<string, unknown> | null;
  created_at: string;
};

export type TransactionPage = {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateTransactionRequest = {
  cart_id?: string;
  checkout_id?: string;
  actor_type?: AuditActorType;
  actor_id?: string;
  reason?: string;
};

export type TransitionTransactionRequest = {
  to_state: TransactionState;
  cart_id?: string;
  checkout_id?: string;
  failure_reason?: string;
  actor_type?: AuditActorType;
  actor_id?: string;
  reason?: string;
};

export async function createTransaction(
  request: CreateTransactionRequest,
): Promise<Transaction> {
  return apiPost<Transaction>("/api/transactions", request);
}

/** The backend code `create_transaction`/`transition_transaction` raise
 * when a checkout already has a transaction — carries `transaction_id` in
 * its structured detail (`CheckoutAlreadyHasTransactionError.detail()`) so
 * a caller can recover it, not just detect the conflict. */
export const TRANSACTION_ALREADY_EXISTS_CODE = "transaction_already_exists";

/** Pulls `transaction_id` out of a `transaction_already_exists` `ApiError`.
 * Returns `undefined` for any other error (including a same-code error
 * whose body is somehow missing the field) — callers should fall back to
 * `getTransactionByCheckout` in that case rather than trust an absent id. */
export function transactionIdFromDuplicateError(err: unknown): string | undefined {
  if (!(err instanceof ApiError) || err.code !== TRANSACTION_ALREADY_EXISTS_CODE) {
    return undefined;
  }
  const id = err.detail.transaction_id;
  return typeof id === "string" ? id : undefined;
}

export async function listTransactions(params?: {
  limit?: number;
  offset?: number;
}): Promise<TransactionPage> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet<TransactionPage>(`/api/transactions${qs ? `?${qs}` : ""}`);
}

export async function getTransaction(transactionId: string): Promise<Transaction> {
  return apiGet<Transaction>(`/api/transactions/${transactionId}`);
}

/** The recovery lookup: given a checkout id, find the transaction anchored
 * to it — the same resource `transactionIdFromDuplicateError` points at,
 * fetched fresh rather than trusted from an error's embedded id. */
export async function getTransactionByCheckout(checkoutId: string): Promise<Transaction> {
  return apiGet<Transaction>(`/api/transactions/by-checkout/${checkoutId}`);
}

export async function transitionTransaction(
  transactionId: string,
  request: TransitionTransactionRequest,
): Promise<Transaction> {
  return apiPost<Transaction>(`/api/transactions/${transactionId}/transitions`, request);
}

export async function listAuditEvents(transactionId: string): Promise<AuditEvent[]> {
  return apiGet<AuditEvent[]>(`/api/transactions/${transactionId}/audit-events`);
}
