import { StatusBadge } from "@/components/ui/badge";
import { Field, FieldGrid } from "@/components/ui/card";
import { Money } from "@/components/ui/money";
import { EmptyState } from "@/components/ui/empty-state";
import { explainReason } from "@/lib/reason-explanations";
import { formatDateTime } from "@/lib/format";
import type { PolicyDecision } from "@/lib/api";

/**
 * Section C. Every field here is a direct pass-through of
 * `PolicyDecisionRead` — the decision itself, and whether it's since been
 * authorized, are read verbatim from `app.commerce.policy.service`'s own
 * output. The only thing computed client-side is the width of the
 * amount-vs-limit bar below, which is a presentation of two numbers the
 * backend already disclosed (`amount_minor_units`, `autonomous_limit_minor_units`)
 * — not a re-derivation of the decision itself, which is shown as-is via
 * `decision`.
 */
export function PolicyPanel({ decision }: { decision: PolicyDecision | null }) {
  if (!decision) {
    return <EmptyState>Not evaluated against policy yet.</EmptyState>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <StatusBadge value={decision.decision} />
        {decision.decision !== "deny" && (
          <StatusBadge
            value={decision.authorized ? "authorized" : "pending"}
            tone={decision.authorized ? "success" : "neutral"}
            label={decision.authorized ? "Authorized" : "Not authorized"}
          />
        )}
      </div>

      <AmountVsLimitBar decision={decision} />

      <p className="text-sm text-zinc-700 dark:text-zinc-300">{explainReason(decision.reason)}</p>

      <FieldGrid>
        <Field label="Amount">
          <Money minorUnits={decision.amount_minor_units} currency={decision.currency} />
        </Field>
        <Field label="Autonomous limit">
          <Money minorUnits={decision.autonomous_limit_minor_units} currency={decision.currency} />
        </Field>
        <Field label="Policy version">
          {decision.policy_version === 0 ? "default (unset)" : decision.policy_version}
        </Field>
        <Field label="Reason code">
          <span className="font-mono text-xs">{decision.reason}</span>
        </Field>
        {decision.authorized && (
          <Field label="Authorized at">{formatDateTime(decision.authorized_at!)}</Field>
        )}
      </FieldGrid>
    </div>
  );
}

/** A single bar comparing this decision's amount against the limit it was
 * measured against — both numbers straight from the backend. Amber/red
 * once the amount reaches the limit, matching the decision's own tone. */
function AmountVsLimitBar({ decision }: { decision: PolicyDecision }) {
  const limit = decision.autonomous_limit_minor_units;
  const amount = decision.amount_minor_units;
  const ratio = limit > 0 ? amount / limit : amount > 0 ? 1 : 0;
  const fillPercent = Math.min(ratio, 1) * 100;
  const overLimit = amount > limit;

  return (
    <div className="flex flex-col gap-1">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div
          className={`h-full rounded-full ${overLimit ? "bg-rose-500" : "bg-emerald-500"}`}
          style={{ width: `${fillPercent}%` }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-zinc-400 dark:text-zinc-500">
        <span>
          <Money minorUnits={amount} currency={decision.currency} /> checkout
        </span>
        <span>
          <Money minorUnits={limit} currency={decision.currency} /> limit
        </span>
      </div>
    </div>
  );
}
