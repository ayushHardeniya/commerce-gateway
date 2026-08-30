"use client";

import { useState } from "react";
import { listTransactions } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { EmptyState, LoadingState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import {
  TRANSACTION_LIST_GRID_COLS,
  TransactionListRow,
} from "@/components/transaction/transaction-list-row";

const PAGE_SIZE = 10;

/** The list view over `GET /api/transactions` (M6B/M7B) — deterministically
 * ordered, newest first, by the backend's own `sequence` column; this page
 * only ever asks for a page (`limit`/`offset`), never sorts or filters
 * client-side. */
export default function TransactionsPage() {
  const [offset, setOffset] = useState(0);
  const transactions = useResource(
    () => listTransactions({ limit: PAGE_SIZE, offset }),
    [offset],
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 px-4 py-6 sm:px-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Control surface
        </p>
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Transactions</h1>
      </div>

      {transactions.status === "loading" && <LoadingState>Loading transactions…</LoadingState>}
      {transactions.status === "error" && (
        <ErrorBanner error={transactions.error} onRetry={transactions.reload} />
      )}
      {transactions.status === "loaded" && transactions.data.items.length === 0 && (
        <EmptyState>No transactions yet.</EmptyState>
      )}

      {transactions.status === "loaded" && transactions.data.items.length > 0 && (
        <>
          <div
            className={`hidden gap-x-3 px-4 text-[11px] font-medium uppercase tracking-wide text-zinc-400 sm:grid dark:text-zinc-600 ${TRANSACTION_LIST_GRID_COLS}`}
          >
            <span>Transaction</span>
            <span className="text-right">Amount</span>
            <span>State</span>
            <span>Payment</span>
            <span className="text-right">Updated</span>
          </div>

          <div className="flex flex-col gap-2">
            {transactions.data.items.map((transaction) => (
              <TransactionListRow key={transaction.id} transaction={transaction} />
            ))}
          </div>

          <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <span>
              {transactions.data.offset + 1}–
              {Math.min(
                transactions.data.offset + transactions.data.items.length,
                transactions.data.total,
              )}{" "}
              of {transactions.data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded border border-black/10 px-2 py-1 font-medium disabled:opacity-40 dark:border-white/10"
              >
                Prev
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= transactions.data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded border border-black/10 px-2 py-1 font-medium disabled:opacity-40 dark:border-white/10"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
