import Link from "next/link";
import { StatusBadge } from "@/components/ui/badge";
import { Money } from "@/components/ui/money";
import { formatDateTime, shortId } from "@/lib/format";
import type { PaymentStatus, TransactionState } from "@/lib/api";

type LoadableValue<T> = T | null | "loading";

/**
 * The masthead: everything section A asks for in one glanceable band —
 * transaction identity, merchant, order amount, current state, and payment
 * status where known. Each field is independently loadable (merchant/amount
 * come from the cart/checkout, payment from its own resource) since they
 * resolve at different points in a transaction's life; a field that isn't
 * loaded yet renders as a quiet placeholder rather than blocking the rest
 * of the header.
 */
export function SummaryHeader({
  id,
  state,
  failureReason,
  createdAt,
  merchant,
  amount,
  paymentStatus,
}: {
  id: string;
  state: TransactionState;
  failureReason: string | null;
  createdAt: string;
  merchant: LoadableValue<{ name: string; slug: string }>;
  amount: LoadableValue<{ minorUnits: number; currency: string }>;
  paymentStatus: LoadableValue<PaymentStatus>;
}) {
  return (
    <div className="rounded-xl border border-black/10 bg-white px-5 py-4 dark:border-white/10 dark:bg-zinc-950">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
            Transaction
          </p>
          <h1
            className="font-mono text-base font-semibold text-zinc-900 sm:text-lg dark:text-zinc-50"
            title={id}
          >
            {shortId(id)}
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-500">
            Opened {formatDateTime(createdAt)}
          </p>
        </div>

        <div className="flex flex-col items-end gap-1.5">
          <StatusBadge value={state} size="lg" />
          {failureReason && (
            <p className="max-w-xs text-right text-xs text-zinc-500 dark:text-zinc-400">
              {failureReason}
            </p>
          )}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-black/5 pt-4 sm:grid-cols-3 dark:border-white/5">
        <SummaryField label="Merchant">
          {merchant === "loading" ? (
            <Placeholder />
          ) : merchant ? (
            <Link
              href={`/merchant`}
              className="text-sm font-medium text-zinc-900 underline decoration-zinc-300 underline-offset-2 hover:decoration-zinc-500 dark:text-zinc-100 dark:decoration-zinc-700"
            >
              {merchant.name}
            </Link>
          ) : (
            <NotYetKnown />
          )}
        </SummaryField>

        <SummaryField label="Amount">
          {amount === "loading" ? (
            <Placeholder />
          ) : amount ? (
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              <Money minorUnits={amount.minorUnits} currency={amount.currency} />
            </span>
          ) : (
            <NotYetKnown />
          )}
        </SummaryField>

        <SummaryField label="Payment">
          {paymentStatus === "loading" ? (
            <Placeholder />
          ) : paymentStatus ? (
            <StatusBadge value={paymentStatus} />
          ) : (
            <NotYetKnown text="Not initiated" />
          )}
        </SummaryField>
      </div>
    </div>
  );
}

function SummaryField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </p>
      {children}
    </div>
  );
}

function Placeholder() {
  return <span className="text-sm text-zinc-300 dark:text-zinc-700">···</span>;
}

function NotYetKnown({ text = "—" }: { text?: string }) {
  return <span className="text-sm text-zinc-400 dark:text-zinc-600">{text}</span>;
}
