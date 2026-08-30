import { Fragment } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { toneFor, TONE_DOT_CLASSES } from "@/lib/status-tone";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { AuditEvent, TransactionState } from "@/lib/api";

/**
 * Section B. Renders exactly the path this transaction actually took — one
 * step per `AuditEvent.to_state`, in `sequence` order — never a
 * hypothetical "what usually comes next." The frontend has no copy of the
 * transaction FSM (`app.commerce.transaction.service._TRANSITIONS`);
 * showing only history that already happened means it never needs one, and
 * a transaction that takes an unusual path (retried, cancelled, failed and
 * recovered) still renders correctly with no special-casing here.
 *
 * A horizontal, connected step track — scrolls rather than wraps on narrow
 * viewports, so the connecting line always stays meaningful.
 */
export function StateProgress({
  currentState,
  auditEvents,
}: {
  currentState: TransactionState;
  auditEvents: AuditEvent[];
}) {
  const steps =
    auditEvents.length > 0
      ? auditEvents.map((event) => ({ state: event.to_state, at: event.created_at }))
      : [{ state: currentState, at: null }];

  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-max items-start gap-0 py-1">
        {steps.map((step, index) => {
          const isCurrent = index === steps.length - 1;
          const tone = toneFor(step.state);
          return (
            <Fragment key={`${step.state}-${index}`}>
              {index > 0 && (
                <div className="mt-[7px] h-px w-8 shrink-0 bg-zinc-200 sm:w-14 dark:bg-zinc-800" />
              )}
              <div className="flex w-20 shrink-0 flex-col items-center gap-1.5 text-center sm:w-28">
                <span
                  className={`h-3.5 w-3.5 shrink-0 rounded-full ${TONE_DOT_CLASSES[tone]} ${
                    isCurrent ? "ring-2 ring-offset-2 ring-zinc-400 ring-offset-white dark:ring-zinc-600 dark:ring-offset-black" : ""
                  }`}
                />
                <StatusBadge value={step.state} />
                {step.at && (
                  <span className="text-[10px] text-zinc-400 dark:text-zinc-600" title={formatDateTime(step.at)}>
                    {formatRelative(step.at)}
                  </span>
                )}
              </div>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
