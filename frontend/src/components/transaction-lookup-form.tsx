"use client";

/**
 * There is no "list transactions" backend endpoint (M6B only added
 * create/get/transition/audit-events for one transaction at a time) — this
 * is the practical way to reach `/transactions/[id]` without inventing one:
 * a direct id lookup, the same shape the transaction/checkout/payment APIs
 * themselves already work in.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

export function TransactionLookupForm() {
  const router = useRouter();
  const [value, setValue] = useState("");

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const id = value.trim();
    if (id) router.push(`/transactions/${encodeURIComponent(id)}`);
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-1.5">
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Transaction id…"
        aria-label="Look up a transaction by id"
        className="w-full min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-xs text-black placeholder:text-zinc-400 focus:outline-none sm:w-44 sm:flex-none sm:focus:w-56 dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50 transition-[width]"
      />
      <button
        type="submit"
        className="rounded-md border border-black/10 px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-zinc-900"
      >
        Open
      </button>
    </form>
  );
}
