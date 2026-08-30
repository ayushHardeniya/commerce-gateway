/**
 * Presentation-only formatting. Nothing here computes an authoritative
 * value — nothing here does arithmetic. `formatMoney` renders the exact
 * integer minor-units amount the backend returned
 * (`docs/decisions/0002-money-as-integer-minor-units.md`); the currency's
 * decimal-digit count comes from `Intl.NumberFormat`'s own resolved options
 * rather than a hand-maintained currency table.
 */

/** ISO 4217's minor-unit exponent for `currency`, read off `Intl` itself
 * rather than a hand-maintained table (falls back to 2, the common case,
 * if the runtime doesn't resolve one). */
function currencyDigits(currency: string): number {
  const formatter = new Intl.NumberFormat(undefined, { style: "currency", currency });
  return formatter.resolvedOptions().maximumFractionDigits ?? 2;
}

export function formatMoney(minorUnits: number, currency: string): string {
  const formatter = new Intl.NumberFormat(undefined, { style: "currency", currency });
  const majorUnits = minorUnits / 10 ** currencyDigits(currency);
  return formatter.format(majorUnits);
}

/**
 * The inverse of `formatMoney`: turns a human-typed decimal amount (e.g. a
 * merchant typing "50.00" into a policy-limit form) into the integer minor
 * units the backend's `autonomous_limit_minor_units` field expects. This
 * parses the operator's own input into the wire format their own form
 * submits — it does not compute, validate, or default a business value; the
 * backend still owns whether the resulting limit is accepted.
 */
export function toMinorUnits(majorAmount: number, currency: string): number {
  return Math.round(majorAmount * 10 ** currencyDigits(currency));
}

/** The inverse of `toMinorUnits` — for prefilling an editable amount input
 * from a value the backend already returned. */
export function toMajorUnits(minorUnits: number, currency: string): number {
  return minorUnits / 10 ** currencyDigits(currency);
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(iso));
}

export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diffSeconds = Math.round((then - Date.now()) / 1000);
  const divisions: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 60 * 60 * 24 * 365],
    ["month", 60 * 60 * 24 * 30],
    ["day", 60 * 60 * 24],
    ["hour", 60 * 60],
    ["minute", 60],
    ["second", 1],
  ];
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, secondsInUnit] of divisions) {
    if (Math.abs(diffSeconds) >= secondsInUnit || unit === "second") {
      return rtf.format(Math.round(diffSeconds / secondsInUnit), unit);
    }
  }
  return rtf.format(0, "second");
}

/** A short, human-scannable id — the full UUID is still in the DOM (title
 * attribute / copy target), this is just what's displayed inline. */
export function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

/** `"policy_denied"` -> `"Policy denied"` — for state/status/error codes the
 * backend already returns as stable snake_case identifiers. */
export function humanize(code: string): string {
  const words = code.split("_");
  return words.map((word, i) => (i === 0 ? capitalize(word) : word)).join(" ");
}

function capitalize(word: string): string {
  return word.length === 0 ? word : word[0].toUpperCase() + word.slice(1);
}
