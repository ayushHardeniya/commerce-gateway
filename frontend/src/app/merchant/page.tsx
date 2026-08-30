"use client";

import { useState } from "react";
import { getMerchantPolicy, listMerchantProducts, listMerchants } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { Card, Field, FieldGrid } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { EmptyState, LoadingState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Money } from "@/components/ui/money";
import { MerchantPolicyForm } from "@/components/merchant/policy-form";
import { formatDateTime } from "@/lib/format";

const PRODUCTS_PER_PAGE = 10;

export default function MerchantPage() {
  const merchants = useResource(() => listMerchants(), []);
  // No separate "default selection" effect: an explicit pick overrides this,
  // otherwise the first loaded merchant is used — computed at render time
  // rather than mirrored into state.
  const [selectedSlugOverride, setSelectedSlugOverride] = useState<string | null>(null);
  const [productQuery, setProductQuery] = useState("");
  const [productOffset, setProductOffset] = useState(0);

  const selectedMerchant =
    merchants.status === "loaded"
      ? (merchants.data.find((m) => m.slug === selectedSlugOverride) ?? merchants.data[0] ?? null)
      : null;
  const selectedSlug = selectedMerchant?.slug ?? null;

  const products = useResource(
    () => listMerchantProducts(selectedSlug ?? "", { q: productQuery || undefined, limit: PRODUCTS_PER_PAGE, offset: productOffset }),
    [selectedSlug, productQuery, productOffset],
    { skip: !selectedSlug },
  );

  const policy = useResource(
    () => getMerchantPolicy(selectedMerchant?.id ?? ""),
    [selectedMerchant?.id],
    { skip: !selectedMerchant, emptyCodes: ["policy_not_found"] },
  );

  const currentPolicy = policy.status === "loaded" ? policy.data : null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 px-4 py-6 sm:px-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Merchant control surface
        </p>
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Merchant</h1>
      </div>

      {merchants.status === "loading" && <LoadingState>Loading merchants…</LoadingState>}
      {merchants.status === "error" && (
        <ErrorBanner error={merchants.error} onRetry={merchants.reload} />
      )}
      {merchants.status === "loaded" && merchants.data.length === 0 && (
        <EmptyState>No merchants exist yet.</EmptyState>
      )}

      {merchants.status === "loaded" && merchants.data.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {merchants.data.map((merchant) => (
            <button
              key={merchant.id}
              type="button"
              onClick={() => {
                setSelectedSlugOverride(merchant.slug);
                setProductOffset(0);
              }}
              className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
                merchant.slug === selectedSlug
                  ? "bg-zinc-900 text-white ring-zinc-900 dark:bg-zinc-50 dark:text-black dark:ring-zinc-50"
                  : "text-zinc-600 ring-black/10 hover:bg-zinc-100 dark:text-zinc-400 dark:ring-white/10 dark:hover:bg-zinc-900"
              }`}
            >
              {merchant.name}
            </button>
          ))}
        </div>
      )}

      {selectedMerchant && (
        <>
          <Card
            title="Merchant"
            action={<StatusBadge value={selectedMerchant.active ? "active" : "inactive"} />}
          >
            <FieldGrid>
              <Field label="Name">{selectedMerchant.name}</Field>
              <Field label="Slug">
                <span className="font-mono text-xs">{selectedMerchant.slug}</span>
              </Field>
              <Field label="Created">{formatDateTime(selectedMerchant.created_at)}</Field>
              {selectedMerchant.description && (
                <Field label="Description">{selectedMerchant.description}</Field>
              )}
            </FieldGrid>
          </Card>

          <Card title="Autonomous transaction policy">
            <div className="flex flex-col gap-3">
              {policy.status === "loading" ? (
                <LoadingState />
              ) : policy.status === "error" ? (
                <ErrorBanner error={policy.error} onRetry={policy.reload} />
              ) : currentPolicy ? (
                <FieldGrid>
                  <Field label="Autonomous limit">
                    <Money
                      minorUnits={currentPolicy.autonomous_limit_minor_units}
                      currency={currentPolicy.currency}
                    />
                  </Field>
                  <Field label="Version">{currentPolicy.version}</Field>
                  <Field label="Updated">{formatDateTime(currentPolicy.updated_at)}</Field>
                </FieldGrid>
              ) : (
                <EmptyState>
                  No policy configured — every non-zero checkout currently requires human
                  authorization.
                </EmptyState>
              )}
              <MerchantPolicyForm
                merchantId={selectedMerchant.id}
                current={currentPolicy}
                onSaved={() => policy.reload()}
              />
            </div>
          </Card>

          <Card title="Catalog">
            <div className="flex flex-col gap-3">
              <input
                type="text"
                value={productQuery}
                onChange={(event) => {
                  setProductQuery(event.target.value);
                  setProductOffset(0);
                }}
                placeholder="Search products…"
                className="w-full max-w-xs rounded-md border border-black/10 bg-white px-2.5 py-1.5 text-sm text-black dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50"
              />

              {products.status === "loading" && <LoadingState />}
              {products.status === "error" && (
                <ErrorBanner error={products.error} onRetry={products.reload} />
              )}
              {products.status === "loaded" && products.data.items.length === 0 && (
                <EmptyState>No products match.</EmptyState>
              )}
              {products.status === "loaded" && products.data.items.length > 0 && (
                <>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-black/10 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-white/10">
                        <th className="py-1.5 font-medium">Product</th>
                        <th className="py-1.5 font-medium">Price</th>
                        <th className="py-1.5 font-medium">Stock</th>
                        <th className="py-1.5 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {products.data.items.map((product) => (
                        <tr
                          key={product.id}
                          className="border-b border-black/5 last:border-0 dark:border-white/5"
                        >
                          <td className="py-1.5">
                            {product.name}{" "}
                            <span className="font-mono text-xs text-zinc-400">{product.sku}</span>
                          </td>
                          <td className="py-1.5">
                            <Money minorUnits={product.price_minor_units} currency={product.currency} />
                          </td>
                          <td className="py-1.5">{product.stock_quantity}</td>
                          <td className="py-1.5">
                            <StatusBadge
                              value={product.is_available ? "available" : "unavailable"}
                              tone={product.is_available ? "success" : "neutral"}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="flex items-center justify-between text-xs text-zinc-500">
                    <span>
                      {products.data.offset + 1}–
                      {Math.min(products.data.offset + products.data.items.length, products.data.total)} of{" "}
                      {products.data.total}
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={productOffset === 0}
                        onClick={() => setProductOffset(Math.max(0, productOffset - PRODUCTS_PER_PAGE))}
                        className="rounded border border-black/10 px-2 py-1 font-medium disabled:opacity-40 dark:border-white/10"
                      >
                        Prev
                      </button>
                      <button
                        type="button"
                        disabled={productOffset + PRODUCTS_PER_PAGE >= products.data.total}
                        onClick={() => setProductOffset(productOffset + PRODUCTS_PER_PAGE)}
                        className="rounded border border-black/10 px-2 py-1 font-medium disabled:opacity-40 dark:border-white/10"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
