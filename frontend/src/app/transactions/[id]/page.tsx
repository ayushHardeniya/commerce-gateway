"use client";

import { use } from "react";
import {
  getCart,
  getCheckout,
  getPayment,
  getPolicyDecision,
  getTransaction,
  listAuditEvents,
} from "@/lib/api";
import { usePolling, useResource } from "@/lib/use-resource";
import { isTerminalTransactionState } from "@/lib/transaction-lifecycle";
import { Card } from "@/components/ui/card";
import { EmptyState, LoadingState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { SummaryHeader } from "@/components/transaction/summary-header";
import { TransactionAlert } from "@/components/transaction/transaction-alert";
import { StateProgress } from "@/components/transaction/state-progress";
import { OrderSummary } from "@/components/transaction/order-summary";
import { PolicyPanel } from "@/components/transaction/policy-panel";
import { PaymentPanel } from "@/components/transaction/payment-panel";
import { AuditTrail } from "@/components/transaction/audit-trail";

export default function TransactionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const transaction = useResource(() => getTransaction(id), [id]);
  const auditEvents = useResource(() => listAuditEvents(id), [id]);

  const cartId = transaction.status === "loaded" ? transaction.data.cart_id : null;
  const checkoutId = transaction.status === "loaded" ? transaction.data.checkout_id : null;

  const cart = useResource(() => getCart(cartId ?? ""), [cartId], { skip: !cartId });
  const checkout = useResource(() => getCheckout(checkoutId ?? ""), [checkoutId], {
    skip: !checkoutId,
  });
  const payment = useResource(() => getPayment(checkoutId ?? ""), [checkoutId], {
    skip: !checkoutId,
    emptyCodes: ["payment_not_found"],
  });
  const policy = useResource(() => getPolicyDecision(checkoutId ?? ""), [checkoutId], {
    skip: !checkoutId,
    emptyCodes: ["policy_decision_not_found"],
  });

  function refreshAll() {
    transaction.reload();
    auditEvents.reload();
    cart.reload();
    checkout.reload();
    payment.reload();
    policy.reload();
  }

  // M7D: while the transaction hasn't reached a terminal outcome, poll the
  // same resources in the background so the page reflects progress made
  // elsewhere (another tab authorizing it, a payment completing) without a
  // manual refresh. `silentReload` avoids flashing every panel back to a
  // loading state on each tick; `usePolling` itself stops the interval the
  // moment `enabled` goes false (a terminal state) or the page unmounts.
  const isPolling = transaction.status === "loaded" && !isTerminalTransactionState(transaction.data.state);
  usePolling(
    () => {
      transaction.silentReload();
      auditEvents.silentReload();
      cart.silentReload();
      checkout.silentReload();
      payment.silentReload();
      policy.silentReload();
    },
    { intervalMs: 5000, enabled: isPolling },
  );

  const merchant =
    cart.status === "loading"
      ? "loading"
      : cart.status === "loaded"
        ? (cart.data.items[0]?.product.merchant ?? null)
        : null;

  const amount =
    checkout.status === "loading"
      ? "loading"
      : checkout.status === "loaded"
        ? { minorUnits: checkout.data.total_minor_units, currency: checkout.data.currency }
        : null;

  const paymentStatus =
    !checkoutId
      ? null
      : payment.status === "loading"
        ? "loading"
        : payment.status === "loaded"
          ? payment.data.status
          : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 px-4 py-6 sm:px-6">
      {transaction.status === "loading" && <LoadingState>Loading transaction…</LoadingState>}
      {transaction.status === "error" && (
        <ErrorBanner error={transaction.error} onRetry={transaction.reload} />
      )}

      {transaction.status === "loaded" && (
        <>
          <SummaryHeader
            id={transaction.data.id}
            state={transaction.data.state}
            failureReason={transaction.data.failure_reason}
            createdAt={transaction.data.created_at}
            merchant={merchant}
            amount={amount}
            paymentStatus={paymentStatus}
          />

          <TransactionAlert
            transaction={transaction.data}
            policy={policy.status === "loaded" ? policy.data : null}
            payment={payment.status === "loaded" ? payment.data : null}
            onAuthorized={refreshAll}
          />

          <Card
            title="Progression"
            action={
              <div className="flex items-center gap-3">
                {isPolling && (
                  <span className="flex items-center gap-1.5 text-[11px] text-zinc-400 dark:text-zinc-500">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                    Live
                  </span>
                )}
                <button
                  type="button"
                  onClick={refreshAll}
                  className="shrink-0 rounded-md border border-black/10 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-zinc-900"
                >
                  Refresh
                </button>
              </div>
            }
          >
            {auditEvents.status === "loading" && <LoadingState />}
            {auditEvents.status === "error" && (
              <ErrorBanner error={auditEvents.error} onRetry={auditEvents.reload} />
            )}
            {auditEvents.status === "loaded" && (
              <StateProgress currentState={transaction.data.state} auditEvents={auditEvents.data} />
            )}
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card title="Order">
              {!transaction.data.checkout_id ? (
                <EmptyState>No checkout linked to this transaction yet.</EmptyState>
              ) : checkout.status === "loading" ? (
                <LoadingState />
              ) : checkout.status === "error" ? (
                <ErrorBanner error={checkout.error} onRetry={checkout.reload} />
              ) : (
                <OrderSummary checkout={checkout.status === "loaded" ? checkout.data : null} />
              )}
            </Card>

            <Card title="Policy">
              {!transaction.data.checkout_id ? (
                <EmptyState>No checkout linked to this transaction yet.</EmptyState>
              ) : policy.status === "loading" ? (
                <LoadingState />
              ) : policy.status === "error" ? (
                <ErrorBanner error={policy.error} onRetry={policy.reload} />
              ) : (
                <PolicyPanel decision={policy.status === "loaded" ? policy.data : null} />
              )}
            </Card>

            <Card title="Payment">
              {transaction.data.checkout_id && payment.status === "loading" ? (
                <LoadingState />
              ) : payment.status === "error" ? (
                <ErrorBanner error={payment.error} onRetry={payment.reload} />
              ) : (
                <PaymentPanel
                  payment={payment.status === "loaded" ? payment.data : null}
                  policy={policy.status === "loaded" ? policy.data : null}
                  hasCheckout={Boolean(transaction.data.checkout_id)}
                />
              )}
            </Card>
          </div>

          <Card title="Audit trail">
            {auditEvents.status === "loading" && <LoadingState />}
            {auditEvents.status === "error" && (
              <ErrorBanner error={auditEvents.error} onRetry={auditEvents.reload} />
            )}
            {auditEvents.status === "loaded" && <AuditTrail events={auditEvents.data} />}
          </Card>
        </>
      )}
    </div>
  );
}
