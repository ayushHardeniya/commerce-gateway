/**
 * Typed client for `/api/carts` — mirrors `app.commerce.cart.schemas`.
 * M7C's only use of it: `Checkout` carries no merchant reference of its
 * own (only `cart_id`), so the transaction detail page reads the cart to
 * show which merchant a transaction belongs to — via its own `merchant_id`
 * or, more usefully, the merchant embedded on any line item's product.
 */

import { apiGet } from "./client";
import type { Product } from "./catalog";

export type CartItem = {
  id: string;
  product_id: string;
  product: Product;
  quantity: number;
  unit_price_minor_units: number;
  subtotal_minor_units: number;
  created_at: string;
  updated_at: string;
};

export type Cart = {
  id: string;
  merchant_id: string;
  currency: string | null;
  items: CartItem[];
  subtotal_minor_units: number;
  created_at: string;
  updated_at: string;
};

export async function getCart(cartId: string): Promise<Cart> {
  return apiGet<Cart>(`/api/carts/${cartId}`);
}
