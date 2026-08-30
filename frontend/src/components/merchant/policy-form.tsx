"use client";

import { useState } from "react";
import { upsertMerchantPolicy, type MerchantPolicy } from "@/lib/api";
import { toMajorUnits, toMinorUnits } from "@/lib/format";
import { describeError } from "@/components/ui/error-banner";

/**
 * Sets the merchant's autonomous spending limit — the one input to
 * `app.commerce.policy.service`'s deterministic ALLOW / REQUIRE_AUTHORIZATION
 * / DENY decision. This form does not decide anything: it submits the
 * operator's chosen limit/currency and shows back whatever the backend
 * persisted (including its `version`, which only the backend increments).
 */
export function MerchantPolicyForm({
  merchantId,
  current,
  onSaved,
}: {
  merchantId: string;
  current: MerchantPolicy | null;
  onSaved: (policy: MerchantPolicy) => void;
}) {
  const [currency, setCurrency] = useState(current?.currency ?? "USD");
  const [amount, setAmount] = useState(() =>
    current ? String(toMajorUnits(current.autonomous_limit_minor_units, current.currency)) : "0",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const parsedAmount = Number(amount);
    const normalizedCurrency = currency.trim().toUpperCase();
    if (!Number.isFinite(parsedAmount) || parsedAmount < 0) {
      setError(new Error("Enter a non-negative amount."));
      return;
    }
    if (normalizedCurrency.length !== 3) {
      setError(new Error("Currency must be a 3-letter ISO 4217 code, e.g. USD."));
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const policy = await upsertMerchantPolicy(merchantId, {
        autonomous_limit_minor_units: toMinorUnits(parsedAmount, normalizedCurrency),
        currency: normalizedCurrency,
      });
      onSaved(policy);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
        Autonomous limit
        <input
          type="number"
          min={0}
          step="0.01"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          className="w-32 rounded-md border border-black/10 bg-white px-2 py-1.5 text-sm text-black dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
        Currency
        <input
          type="text"
          value={currency}
          onChange={(event) => setCurrency(event.target.value)}
          maxLength={3}
          className="w-20 rounded-md border border-black/10 bg-white px-2 py-1.5 text-sm uppercase text-black dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </label>
      <button
        type="submit"
        disabled={saving}
        className="rounded-md bg-black px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
      >
        {saving ? "Saving…" : current ? "Update limit" : "Set limit"}
      </button>
      {error !== null && (
        <p className="w-full text-xs text-rose-600 dark:text-rose-400">
          {describeError(error).message}
        </p>
      )}
    </form>
  );
}
