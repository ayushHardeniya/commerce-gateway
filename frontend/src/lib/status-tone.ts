/**
 * Presentation-only color grouping for the various status/state vocabularies
 * the backend returns (transaction state, checkout status, payment status,
 * policy decision). This never drives a decision — it only picks a badge
 * color — so it's fine for it to live in the frontend even though the
 * values themselves are authoritative backend facts.
 */

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

const TONE_BY_VALUE: Record<string, Tone> = {
  // transaction state
  discovered: "neutral",
  cart_created: "neutral",
  checkout_created: "info",
  policy_pending: "info",
  authorized: "info",
  payment_pending: "warning",
  payment_success: "success",
  order_confirmed: "success",
  policy_denied: "danger",
  payment_failed: "danger",
  checkout_expired: "danger",
  cancelled: "neutral",
  failed: "danger",
  // checkout status
  active: "info",
  completed: "success",
  expired: "danger",
  // payment status
  created: "warning",
  success: "success",
  // policy decision
  allow: "success",
  require_authorization: "warning",
  deny: "danger",
};

export function toneFor(value: string): Tone {
  return TONE_BY_VALUE[value] ?? "neutral";
}

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-500/20 dark:bg-zinc-800 dark:text-zinc-300",
  info: "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-950 dark:text-sky-300",
  success:
    "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-300",
  warning: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300",
  danger: "bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-950 dark:text-rose-300",
};

export const TONE_DOT_CLASSES: Record<Tone, string> = {
  neutral: "bg-zinc-400",
  info: "bg-sky-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-rose-500",
};
