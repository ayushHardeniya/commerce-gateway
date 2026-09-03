"use client";

import { useState } from "react";

const STEPS = [
  {
    n: "01",
    title: "Discover",
    body: "AI Buyer searches the merchant's agent-readable catalog.",
  },
  { n: "02", title: "Cart", body: "The buyer builds a cart using typed commerce tools." },
  {
    n: "03",
    title: "Checkout",
    body: "The application creates a deterministic checkout with validated prices and currency.",
  },
  {
    n: "04",
    title: "Policy",
    body: "Merchant rules determine whether autonomous spending is allowed.",
  },
  { n: "05", title: "Authorize", body: "If required, a human must authorize the transaction." },
  { n: "06", title: "Pay", body: "The authorized checkout is handed to the payment provider." },
  {
    n: "07",
    title: "Audit",
    body: "Transaction state and important actions are recorded.",
  },
] as const;

/**
 * A collapsed-by-default edge tab that expands into a compact "how it
 * works" reference for first-time viewers. Purely informational — no data
 * fetching, no effect on the chat above it. `position: fixed` keeps it out
 * of the page's normal flow entirely, so it overlays rather than reflows
 * the centered chat column (and can never introduce horizontal scrolling).
 */
export function HowItWorksPanel() {
  const [open, setOpen] = useState(true);

  return (
    <div className="pointer-events-none fixed inset-y-0 right-0 z-20 flex flex-row-reverse items-start">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="how-it-works-panel"
        className="pointer-events-auto mt-24 flex h-12 w-10 items-center justify-center rounded-l-md border border-zinc-300 bg-white text-zinc-700 shadow-md hover:bg-zinc-100 sm:mt-28 dark:border-zinc-700 dark:bg-white dark:text-zinc-800"
      >
        <span aria-hidden="true" className="text-base leading-none">
          {open ? "›" : "‹"}
        </span>
      </button>

      {open && (
        <aside
          id="how-it-works-panel"
          className="pointer-events-auto mt-24 flex max-h-[70vh] w-60 max-w-[80vw] flex-col gap-3 overflow-y-auto rounded-l-lg border border-zinc-200 bg-white/95 p-4 shadow-xl sm:mt-28 dark:border-zinc-800 dark:bg-zinc-900/95"
        >

          <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500 dark:text-zinc-300">
            How it works
          </p>
          <ol className="flex flex-col gap-3">
            {STEPS.map((step) => (
              <li key={step.n} className="flex gap-2.5">
                <span className="mt-0.5 shrink-0 font-mono text-[11px] text-zinc-400 dark:text-zinc-600">
                  {step.n}
                </span>
                <div>
                  <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
                    {step.title}
                  </p>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-1 border-t border-black/10 pt-3 font-mono text-[11px] leading-relaxed text-zinc-500 dark:border-white/10 dark:text-zinc-500">
            LLM proposes actions.
            <br />
            Application validates and executes them.
          </p>
        </aside>
      )}
    </div>
  );
}
