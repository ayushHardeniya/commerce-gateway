import { StatusBadge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { toneFor, TONE_DOT_CLASSES } from "@/lib/status-tone";
import { formatDateTime, shortId } from "@/lib/format";
import type { AuditEvent } from "@/lib/api";

/** Metadata keys `app.commerce.transaction.service`'s guards actually set
 * (see each `_guard_*`'s `"metadata"` return), mapped to a display label —
 * purely presentational, not a copy of any business rule. A key not listed
 * here still isn't lost: it falls into the raw-JSON fallback below rather
 * than being silently dropped, so this table never needs to be exhaustive. */
const METADATA_LABELS: Record<string, string> = {
  policy_decision_id: "Policy decision",
  policy_decision: "Decision",
  authorization_id: "Authorization",
  payment_id: "Payment",
  provider_order_id: "Provider order",
  provider_payment_id: "Provider payment",
  checkout_id: "Checkout",
  failure_code: "Failure code",
  expired_at: "Expired at",
};

const ID_LIKE_KEY = /_id$/;

function formatMetadataValue(key: string, value: unknown): string {
  if (typeof value !== "string") return JSON.stringify(value);
  if (key.endsWith("_at")) return formatDateTime(value);
  if (ID_LIKE_KEY.test(key) && value.length > 12) return shortId(value);
  return value;
}

/** The full, append-only history behind a transaction — every field here is
 * exactly what `app.commerce.transaction.service` wrote, in `sequence`
 * order (the backend's own deterministic ordering key). Nothing is
 * summarized or reinterpreted, only reformatted for readability. */
export function AuditTrail({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) {
    return <EmptyState>No audit events yet.</EmptyState>;
  }

  return (
    <ol className="flex flex-col">
      {events.map((event, index) => {
        const isLast = index === events.length - 1;
        const dotTone = toneFor(event.to_state);
        const metadataEntries = Object.entries(event.event_metadata ?? {});
        const knownEntries = metadataEntries.filter(([key]) => key in METADATA_LABELS);
        const unknownMetadata = Object.fromEntries(
          metadataEntries.filter(([key]) => !(key in METADATA_LABELS)),
        );

        return (
          <li
            key={event.id}
            className={`relative flex gap-3 border-zinc-200 pb-5 pl-4 last:pb-0 dark:border-zinc-800 ${
              isLast ? "border-transparent" : "border-l-2"
            }`}
          >
            <span
              className={`absolute -left-[7px] top-0 h-3.5 w-3.5 shrink-0 rounded-full ring-4 ring-white dark:ring-zinc-950 ${TONE_DOT_CLASSES[dotTone]}`}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {event.from_state ? (
                  <>
                    <StatusBadge value={event.from_state} />
                    <span className="text-zinc-400">→</span>
                  </>
                ) : (
                  <span className="text-xs text-zinc-400">created as</span>
                )}
                <StatusBadge value={event.to_state} />
                <span className="ml-auto shrink-0 text-xs text-zinc-500 dark:text-zinc-500">
                  {formatDateTime(event.created_at)}
                </span>
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
                <span className="inline-flex items-center gap-1.5">
                  <ActorTag actorType={event.actor_type} />
                  {event.actor_id && <span className="font-mono">{event.actor_id}</span>}
                </span>
                {event.reason && <span>· {event.reason}</span>}
              </div>

              {knownEntries.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {knownEntries.map(([key, value]) => (
                    <span
                      key={key}
                      className="inline-flex items-center gap-1 rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400"
                      title={typeof value === "string" ? value : undefined}
                    >
                      <span className="text-zinc-400 dark:text-zinc-600">
                        {METADATA_LABELS[key]}
                      </span>
                      <span className="font-mono">{formatMetadataValue(key, value)}</span>
                    </span>
                  ))}
                </div>
              )}

              {Object.keys(unknownMetadata).length > 0 && (
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer select-none text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
                    more metadata
                  </summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-zinc-50 p-2 font-mono text-[11px] text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                    {JSON.stringify(unknownMetadata, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** `actor_type` is the field of record (`"system"` or `"agent"`, per
 * `AUDIT_ACTOR_TYPES` on the backend) — this just renders it as a compact
 * tag instead of raw text. */
function ActorTag({ actorType }: { actorType: string }) {
  const isAgent = actorType === "agent";
  return (
    <span
      className={`rounded px-1 py-px font-mono text-[10px] font-semibold uppercase tracking-wide ${
        isAgent
          ? "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300"
          : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400"
      }`}
    >
      {isAgent ? "AI agent" : "System"}
    </span>
  );
}
