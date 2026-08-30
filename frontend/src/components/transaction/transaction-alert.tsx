"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Money } from "@/components/ui/money";
import { toneFor, TONE_CLASSES } from "@/lib/status-tone";
import { explainReason } from "@/lib/reason-explanations";
import { describeError } from "@/components/ui/error-banner";
import { authorizeCheckout } from "@/lib/api";
import type { Payment, PolicyDecision, Transaction } from "@/lib/api";

/**
 * Section F (M7C) + the authorization action (M7D): make a blocked/failed
 * transaction understandable, and — the one case where a human can
 * actually unblock it from here — let them. This never decides *whether*
 * something is blocked, and the button below never decides whether
 * authorization is *granted*; it only renders what the backend already
 * said and relays the operator's click to the backend's own endpoint:
 *
 * - `Transaction.failure_reason` is non-null exactly when the backend put
 *   this transaction in a failure/terminal-failure state
 *   (`app.commerce.transaction.service`'s own guards only ever set it on
 *   that path) — that alone is the trigger, not a list of state names
 *   copied from the FSM.
 * - "Awaiting authorization" is derived the same way the payment flow
 *   itself already derives it: a `PolicyDecision` of
 *   `require_authorization` with no `CheckoutAuthorization` yet
 *   (`policy.authorized === false`) — both fields the backend returned,
 *   not an inference about FSM transitions.
 * - Granting it calls `POST /api/policy/checkouts/{id}/authorize` with the
 *   checkout's own already-known amount/currency
 *   (`app.commerce.policy.service.authorize_checkout` independently
 *   re-validates both against live state — this call decides nothing);
 *   success only ever means "authorized," never "paid."
 */
export function TransactionAlert({
  transaction,
  policy,
  payment,
  onAuthorized,
}: {
  transaction: Transaction;
  policy: PolicyDecision | null;
  payment: Payment | null;
  onAuthorized?: () => void;
}) {
  if (transaction.failure_reason) {
    const tone = toneFor(transaction.state);
    return (
      <div className={`rounded-lg border px-4 py-3 ring-1 ring-inset ${TONE_CLASSES[tone]}`}>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge value={transaction.state} tone={tone} />
          <p className="text-sm font-medium">{explainReason(transaction.failure_reason)}</p>
        </div>
        <p className="mt-1 font-mono text-xs opacity-70">{transaction.failure_reason}</p>
        {payment?.failure_message && (
          <p className="mt-1 text-xs opacity-80">Provider detail: {payment.failure_message}</p>
        )}
      </div>
    );
  }

  if (policy && policy.decision === "require_authorization" && !policy.authorized) {
    return (
      <div className={`rounded-lg border px-4 py-3 ring-1 ring-inset ${TONE_CLASSES.warning}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge value="require_authorization" />
              <p className="text-sm font-medium">Awaiting human authorization</p>
            </div>
            <p className="mt-1 text-xs opacity-80">
              The checkout total (
              <Money minorUnits={policy.amount_minor_units} currency={policy.currency} />) exceeds
              the merchant&apos;s autonomous limit (
              <Money minorUnits={policy.autonomous_limit_minor_units} currency={policy.currency} />
              ). Authorizing only clears this checkout to be paid — it does not itself charge
              anything.
            </p>
          </div>
          <AuthorizeAction
            checkoutId={policy.checkout_id}
            amountMinorUnits={policy.amount_minor_units}
            currency={policy.currency}
            onAuthorized={onAuthorized}
          />
        </div>
      </div>
    );
  }

  return null;
}

function AuthorizeAction({
  checkoutId,
  amountMinorUnits,
  currency,
  onAuthorized,
}: {
  checkoutId: string;
  amountMinorUnits: number;
  currency: string;
  onAuthorized?: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleClick() {
    setSubmitting(true);
    setError(null);
    try {
      await authorizeCheckout(checkoutId, {
        amount_minor_units: amountMinorUnits,
        currency,
      });
      onAuthorized?.();
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex shrink-0 flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => void handleClick()}
        disabled={submitting}
        className="whitespace-nowrap rounded-md bg-amber-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50 dark:bg-amber-500 dark:text-black"
      >
        {submitting ? "Authorizing…" : "Authorize checkout"}
      </button>
      {error !== null && (
        <p className="max-w-[16rem] text-right text-[11px] text-rose-700 dark:text-rose-400">
          {describeError(error).message}
        </p>
      )}
    </div>
  );
}
