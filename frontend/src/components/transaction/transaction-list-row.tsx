import Link from "next/link";
import { StatusBadge } from "@/components/ui/badge";
import { Money } from "@/components/ui/money";
import { useResource } from "@/lib/use-resource";
import { formatDateTime, shortId } from "@/lib/format";
import { getCart, getCheckout, getPayment } from "@/lib/api";
import type { Transaction } from "@/lib/api";

/** One fixed column template shared verbatim by the header row
 * (`/transactions/page.tsx`) and every `TransactionListRow` — each is its
 * own grid container, so without a shared, explicit template the columns
 * would size independently per row and drift out of alignment with each
 * other and the header. */
export const TRANSACTION_LIST_GRID_COLS = "sm:grid-cols-[1fr_6rem_9rem_7rem_9rem]";

/**
 * One row in `/transactions`. `GET /api/transactions` returns only
 * `TransactionRead` (id/cart_id/checkout_id/state/failure_reason/
 * timestamps) — no merchant, amount, or payment status, since a listing
 * endpoint deliberately doesn't join across domains
 * (`docs/decisions/0008-...md`'s "reference, don't duplicate" principle
 * extends to the API shape too). Each row resolves its own enrichment from
 * the checkout/cart/payment endpoints already used on the detail page, the
 * same way that page does — bounded to whatever's on screen, not the whole
 * list at once, and independently loadable so one slow row never blocks
 * the rest.
 */
export function TransactionListRow({ transaction }: { transaction: Transaction }) {
  const cart = useResource(() => getCart(transaction.cart_id ?? ""), [transaction.cart_id], {
    skip: !transaction.cart_id,
  });
  const checkout = useResource(
    () => getCheckout(transaction.checkout_id ?? ""),
    [transaction.checkout_id],
    { skip: !transaction.checkout_id },
  );
  const payment = useResource(
    () => getPayment(transaction.checkout_id ?? ""),
    [transaction.checkout_id],
    { skip: !transaction.checkout_id, emptyCodes: ["payment_not_found"] },
  );

  const merchantName =
    cart.status === "loaded" ? (cart.data.items[0]?.product.merchant.name ?? null) : null;

  return (
    <Link
      href={`/transactions/${transaction.id}`}
      className={`grid grid-cols-2 items-center gap-x-3 gap-y-1 rounded-lg border border-black/10 bg-white px-4 py-3 text-sm transition-colors hover:border-black/20 hover:bg-zinc-50 dark:border-white/10 dark:bg-zinc-950 dark:hover:border-white/20 dark:hover:bg-zinc-900 ${TRANSACTION_LIST_GRID_COLS}`}
    >
      <div className="col-span-2 min-w-0 sm:col-span-1">
        <p className="truncate font-mono text-xs text-zinc-900 dark:text-zinc-100" title={transaction.id}>
          {shortId(transaction.id)}
        </p>
        <p className="truncate text-xs text-zinc-400 dark:text-zinc-500">
          {merchantName ?? (cart.status === "loading" ? "···" : "Merchant unknown")}
        </p>
      </div>

      <div className="text-xs text-zinc-500 sm:text-right dark:text-zinc-400">
        {checkout.status === "loaded" ? (
          <Money minorUnits={checkout.data.total_minor_units} currency={checkout.data.currency} />
        ) : checkout.status === "loading" ? (
          "···"
        ) : (
          "—"
        )}
      </div>

      <div>
        <StatusBadge value={transaction.state} />
      </div>

      <div>
        {payment.status === "loaded" ? (
          <StatusBadge value={payment.data.status} />
        ) : (
          <span className="text-xs text-zinc-300 dark:text-zinc-700">
            {payment.status === "loading" ? "···" : "—"}
          </span>
        )}
      </div>

      <div className="col-span-2 text-right text-xs text-zinc-400 sm:col-span-1 dark:text-zinc-500">
        {formatDateTime(transaction.updated_at)}
      </div>
    </Link>
  );
}
