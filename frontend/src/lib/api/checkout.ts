/** Typed client for `/api/checkouts` — mirrors `app.commerce.checkout.schemas`. */

import { apiGet } from "./client";

export type CheckoutStatus = "active" | "expired" | "completed" | "cancelled";

export type CheckoutItem = {
  id: string;
  product_id: string | null;
  product_name: string;
  product_sku: string;
  quantity: number;
  unit_price_minor_units: number;
  subtotal_minor_units: number;
};

export type Checkout = {
  id: string;
  cart_id: string;
  status: CheckoutStatus;
  total_minor_units: number;
  currency: string;
  items: CheckoutItem[];
  created_at: string;
  expires_at: string;
};

export async function getCheckout(checkoutId: string): Promise<Checkout> {
  return apiGet<Checkout>(`/api/checkouts/${checkoutId}`);
}
