import Link from "next/link";
import { StatusBadge } from "@/components/ui/badge";
import { Field, FieldGrid } from "@/components/ui/card";
import { Money } from "@/components/ui/money";
import { EmptyState } from "@/components/ui/empty-state";
import { formatDateTime } from "@/lib/format";
import type { Checkout } from "@/lib/api";

/** Section A's "relevant checkout/order information" — a direct render of
 * `CheckoutRead`, including its line items. `checkout.status` is already
 * `Checkout.effective_status` on the backend (folds in expiry), not the
 * raw stored column — nothing here recomputes it. */
export function OrderSummary({ checkout }: { checkout: Checkout | null }) {
  if (!checkout) {
    return <EmptyState>No checkout linked to this transaction yet.</EmptyState>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <StatusBadge value={checkout.status} />
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          <Money minorUnits={checkout.total_minor_units} currency={checkout.currency} />
        </span>
      </div>

      <FieldGrid>
        <Field label="Items">{checkout.items.length}</Field>
        <Field label="Expires">{formatDateTime(checkout.expires_at)}</Field>
      </FieldGrid>

      {checkout.items.length > 0 && (
        <ul className="flex flex-col divide-y divide-black/5 text-sm dark:divide-white/5">
          {checkout.items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="truncate">
                {item.product_name}{" "}
                <span className="font-mono text-xs text-zinc-400">×{item.quantity}</span>
              </span>
              <span className="shrink-0 tabular-nums text-zinc-600 dark:text-zinc-400">
                <Money minorUnits={item.subtotal_minor_units} currency={checkout.currency} />
              </span>
            </li>
          ))}
        </ul>
      )}

      {checkout.status === "active" && (
        <Link
          href={`/pay?checkout_id=${checkout.id}`}
          className="self-start rounded-md bg-black px-3 py-1.5 text-xs font-medium text-white dark:bg-zinc-50 dark:text-black"
        >
          Pay this checkout →
        </Link>
      )}
    </div>
  );
}
