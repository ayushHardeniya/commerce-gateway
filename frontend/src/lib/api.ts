export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Structured `{code, message}` error shape every commerce endpoint returns
 * (see `app.commerce.errors` on the backend) — surfaced as a typed error
 * instead of a generic HTTP failure so the UI can show what actually went
 * wrong (e.g. `invalid_payment_signature`, `authorization_required`).
 */
export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    if (detail?.code) {
      throw new ApiError(detail.code, detail.message ?? "Request failed.");
    }
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

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
  const response = await fetch(`${API_BASE_URL}/api/checkouts/${checkoutId}/payment`, {
    method: "POST",
  });
  return parseOrThrow<PaymentOrder>(response);
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
  const response = await fetch(`${API_BASE_URL}/api/checkouts/${checkoutId}/payment/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseOrThrow<Payment>(response);
}

export async function getPayment(checkoutId: string): Promise<Payment> {
  const response = await fetch(`${API_BASE_URL}/api/checkouts/${checkoutId}/payment`);
  return parseOrThrow<Payment>(response);
}
