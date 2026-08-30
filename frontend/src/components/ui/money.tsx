import { formatMoney } from "@/lib/format";

export function Money({ minorUnits, currency }: { minorUnits: number; currency: string }) {
  return <span className="font-mono tabular-nums">{formatMoney(minorUnits, currency)}</span>;
}
