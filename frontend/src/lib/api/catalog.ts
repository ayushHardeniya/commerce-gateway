/**
 * Typed client for `/api/catalog` — mirrors `app.catalog.schemas` on the
 * backend field-for-field. Nothing here recomputes price, availability, or
 * stock; every field is whatever the backend returned.
 */

import { apiGet } from "./client";

export type Merchant = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
};

export type MerchantSummary = {
  id: string;
  name: string;
  slug: string;
  active: boolean;
};

export type Product = {
  id: string;
  sku: string;
  name: string;
  description: string | null;
  price_minor_units: number;
  currency: string;
  active: boolean;
  stock_quantity: number;
  merchant: MerchantSummary;
  created_at: string;
  updated_at: string;
  is_available: boolean;
};

export type ProductPage = {
  items: Product[];
  total: number;
  limit: number;
  offset: number;
};

export async function listMerchants(): Promise<Merchant[]> {
  return apiGet<Merchant[]>("/api/catalog/merchants");
}

export async function getMerchant(slug: string): Promise<Merchant> {
  return apiGet<Merchant>(`/api/catalog/merchants/${encodeURIComponent(slug)}`);
}

export type ProductSearchParams = {
  q?: string;
  inStockOnly?: boolean;
  includeInactive?: boolean;
  limit?: number;
  offset?: number;
};

function searchQuery(params: ProductSearchParams | undefined): string {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.inStockOnly) query.set("in_stock_only", "true");
  if (params?.includeInactive) query.set("include_inactive", "true");
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export async function listMerchantProducts(
  slug: string,
  params?: ProductSearchParams,
): Promise<ProductPage> {
  return apiGet<ProductPage>(
    `/api/catalog/merchants/${encodeURIComponent(slug)}/products${searchQuery(params)}`,
  );
}

export async function searchProducts(params?: ProductSearchParams): Promise<ProductPage> {
  return apiGet<ProductPage>(`/api/catalog/products${searchQuery(params)}`);
}

export async function getProduct(productId: string): Promise<Product> {
  return apiGet<Product>(`/api/catalog/products/${productId}`);
}
