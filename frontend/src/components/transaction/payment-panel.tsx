import { StatusBadge } from "@/components/ui/badge";
import { Field, FieldGrid } from "@/components/ui/card";
import { Money } from "@/components/ui/money";
import { EmptyState } from "@/components/ui/empty-state";
import { explainReason } from "@/lib/reason-explanations";
import { shortId } from "@/lib/format";
import type { Payment, PolicyDecision } from "@/lib/api";

/**
 * Section E. `payment` is `PaymentRead` verbatim when a `Payment` row
 * exists; `null` only ever means "no payment has been initiated yet" (the
 * `payment_not_found` empty state `useResource` already normalizes). When
 * there's no payment yet, the panel still distinguishes *why* using
 * `policy` — awaiting authorization vs. simply not started — both read
 * directly off `PolicyDecisionRead`, never inferred from transaction state.
 */
export function PaymentPanel({
  payment,
  policy,
  hasCheckout,
}: {
  payment: Payment | null;
  policy: PolicyDecision | null;
  hasCheckout: boolean;
}) {
  if (!hasCheckout) {
    return <EmptyState>No checkout linked to this transaction yet.</EmptyState>;
  }

  if (payment) {
    return (
      <div className="flex flex-col gap-3">
        <StatusBadge value={payment.status} />
        <FieldGrid>
          <Field label="Provider">{payment.provider}</Field>
          <Field label="Amount">
            <Money minorUnits={payment.amount_minor_units} currency={payment.currency} />
          </Field>
          <Field label="Order id">
            <span className="font-mono text-xs" title={payment.provider_order_id}>
              {shortId(payment.provider_order_id)}
            </span>
          </Field>
          {payment.provider_payment_id && (
            <Field label="Payment id">
              <span className="font-mono text-xs" title={payment.provider_payment_id}>
                {shortId(payment.provider_payment_id)}
              </span>
            </Field>
          )}
        </FieldGrid>
        {payment.status === "failed" && payment.failure_code && (
          <p className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:bg-rose-950 dark:text-rose-300">
            {explainReason(payment.failure_code)}
            {payment.failure_message ? ` — ${payment.failure_message}` : ""}
          </p>
        )}
      </div>
    );
  }

  if (policy && policy.decision === "require_authorization" && !policy.authorized) {
    return (
      <div className="flex flex-col gap-2">
        <StatusBadge value="require_authorization" label="Authorization required" />
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Payment cannot be initiated until this checkout is authorized.
        </p>
      </div>
    );
  }

  if (policy && policy.decision === "deny") {
    return (
      <div className="flex flex-col gap-2">
        <StatusBadge value="deny" label="Payment unavailable" />
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          This checkout was denied by policy; it can never be paid.
        </p>
      </div>
    );
  }

  return <EmptyState>No payment initiated yet.</EmptyState>;
}
