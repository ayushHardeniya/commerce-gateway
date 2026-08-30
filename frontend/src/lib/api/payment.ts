/**
 * Typed client for `/api/checkouts/{id}/payment` — mirrors
 * `app.commerce.payment.schemas`. This module only ever relays what the
 * backend decides; it never computes an amount, a currency, or whether a
 * payment succeeded. `src/app/pay/page.tsx` is the one place `initiatePayment`
 * / `confirmPayment` drive the real Razorpay Checkout widget — that
 * integration boundary is unchanged by M7A.
 */

import { apiGet, apiPost } from "./client";

export type PaymentOrder = {
  payment_id: string;
  checkout_id: string;
  provider: string;
  provider_order_id: string;
  amount_minor_units: number;
  currency: string;
  razorpay_key_id: string;
};

export type PaymentStatus = "created" | "success" | "failed";

export type Payment = {
  id: string;
  checkout_id: string;
  provider: string;
  provider_order_id: string;
  provider_payment_id: string | null;
  status: PaymentStatus;
  amount_minor_units: number;
  currency: string;
  failure_code: string | null;
  failure_message: string | null;
  created_at: string;
  updated_at: string;
};

/**
 * Ask the backend to create a Razorpay order for this checkout. Takes no
 * amount/currency: the backend derives both from the checkout's own
 * persisted total — see `app.commerce.payment.service.initiate_payment`.
 */
export async function initiatePayment(checkoutId: string): Promise<PaymentOrder> {
  return apiPost<PaymentOrder>(`/api/checkouts/${checkoutId}/payment`);
}

/** Send Razorpay Checkout's returned identifiers/signature back to the
 * backend for server-side verification. The backend, not this call, decides
 * whether the payment actually succeeded. */
export async function confirmPayment(
  checkoutId: string,
  payload: {
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  },
): Promise<Payment> {
  return apiPost<Payment>(`/api/checkouts/${checkoutId}/payment/confirm`, payload);
}

export async function getPayment(checkoutId: string): Promise<Payment> {
  return apiGet<Payment>(`/api/checkouts/${checkoutId}/payment`);
}
