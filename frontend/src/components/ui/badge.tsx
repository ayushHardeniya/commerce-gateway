import { toneFor, TONE_CLASSES, TONE_DOT_CLASSES, type Tone } from "@/lib/status-tone";
import { humanize } from "@/lib/format";

/**
 * A small pill for a backend-provided status/state string. `tone` is
 * inferred from `value` unless overridden. `label`, when given, replaces
 * the displayed text (`humanize(value)` otherwise) — for the handful of UI-
 * derived states (e.g. "awaiting authorization") that summarize more than
 * one backend field rather than echoing a single enum value verbatim;
 * `value` still drives the tone lookup in that case.
 */
export function StatusBadge({
  value,
  tone,
  label,
  size = "sm",
}: {
  value: string;
  tone?: Tone;
  label?: string;
  size?: "sm" | "lg";
}) {
  const resolvedTone = tone ?? toneFor(value);
  const sizeClasses =
    size === "lg" ? "px-3 py-1 text-sm gap-2" : "px-2.5 py-0.5 text-xs gap-1.5";
  const dotSize = size === "lg" ? "h-2 w-2" : "h-1.5 w-1.5";
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full font-medium ring-1 ring-inset ${sizeClasses} ${TONE_CLASSES[resolvedTone]}`}
    >
      <span className={`shrink-0 rounded-full ${dotSize} ${TONE_DOT_CLASSES[resolvedTone]}`} />
      {label ?? humanize(value)}
    </span>
  );
}
