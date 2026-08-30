/** Typed client for `/api/policy` — mirrors `app.commerce.policy.schemas`.
 * The decision/authorization values here are read-only reflections of what
 * `app.commerce.policy.service` already decided; nothing on the frontend
 * re-evaluates or overrides them. */

import { apiGet, apiPost, apiPut } from "./client";

export type PolicyDecisionValue = "allow" | "require_authorization" | "deny";

export type MerchantPolicy = {
  id: string;
  merchant_id: string;
  version: number;
  autonomous_limit_minor_units: number;
  currency: string;
  created_at: string;
  updated_at: string;
};

export type UpsertMerchantPolicyRequest = {
  autonomous_limit_minor_units: number;
  currency: string;
};

export type PolicyDecision = {
  id: string;
  checkout_id: string;
  decision: PolicyDecisionValue;
  reason: string;
  amount_minor_units: number;
  currency: string;
  policy_version: number;
  autonomous_limit_minor_units: number;
  created_at: string;
  authorized: boolean;
  authorized_at: string | null;
};

export type CheckoutAuthorization = {
  id: string;
  checkout_id: string;
  policy_decision_id: string;
  amount_minor_units: number;
  currency: string;
  created_at: string;
};

export async function getMerchantPolicy(merchantId: string): Promise<MerchantPolicy> {
  return apiGet<MerchantPolicy>(`/api/policy/merchants/${merchantId}`);
}

export async function upsertMerchantPolicy(
  merchantId: string,
  request: UpsertMerchantPolicyRequest,
): Promise<MerchantPolicy> {
  return apiPut<MerchantPolicy>(`/api/policy/merchants/${merchantId}`, request);
}

export async function getPolicyDecision(checkoutId: string): Promise<PolicyDecision> {
  return apiGet<PolicyDecision>(`/api/policy/checkouts/${checkoutId}/decision`);
}

export async function getAuthorization(checkoutId: string): Promise<CheckoutAuthorization> {
  return apiGet<CheckoutAuthorization>(`/api/policy/checkouts/${checkoutId}/authorization`);
}

/**
 * Grants the one-time human authorization a `require_authorization`
 * decision needs before payment can proceed. `amountMinorUnits`/`currency`
 * must be the checkout's own current authoritative total — the backend
 * (`app.commerce.policy.service.authorize_checkout`) independently
 * re-checks both against the live checkout and the original decision
 * snapshot before granting anything, so this call decides nothing on its
 * own; a mismatch (e.g. the checkout's total changed) is rejected
 * server-side, not pre-validated here.
 */
export async function authorizeCheckout(
  checkoutId: string,
  request: { amount_minor_units: number; currency: string },
): Promise<CheckoutAuthorization> {
  return apiPost<CheckoutAuthorization>(`/api/policy/checkouts/${checkoutId}/authorize`, request);
}
