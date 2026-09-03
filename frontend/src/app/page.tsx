"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  chatWithAgent,
  createTransaction,
  fetchHealth,
  getTransactionByCheckout,
  transactionIdFromDuplicateError,
  type ToolCallRecord,
} from "@/lib/api";
import { describeError } from "@/components/ui/error-banner";
import { HowItWorksPanel } from "@/components/how-it-works-panel";

const EXAMPLE_PROMPT = "Find me wireless headphones under $50 and buy one.";

type ChatTurn =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; toolCalls: ToolCallRecord[]; linkedTransactionId?: string }
  | { role: "error"; text: string };

type ApiStatus = "checking" | "online" | "offline";

export default function Home() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  // Tracks checkouts we've already tried to link a transaction to, so a
  // repeated `create_checkout` tool call in this session doesn't keep
  // retrying `POST /api/transactions` against a checkout that already has
  // one (see the M7A report for why there's no lookup-by-checkout endpoint
  // to recover the existing transaction id in that case).
  const attemptedCheckouts = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    function checkHealth() {
      fetchHealth()
        .then(() => {
          if (!cancelled) setApiStatus("online");
        })
        .catch(() => {
          if (!cancelled) setApiStatus("offline");
        });
    }

    checkHealth();
    // A transient Render cold-start failure on the first check shouldn't
    // permanently strand the badge on "offline" — recheck periodically so
    // it can recover once the backend is actually warm. 30s keeps this from
    // polling aggressively.
    const intervalId = setInterval(checkHealth, 30_000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [turns]);

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || sending) return;

    setInput("");
    setTurns((t) => [...t, { role: "user", text: message }]);
    setSending(true);

    try {
      const response = await chatWithAgent(message);
      setApiStatus("online");
      const linkedTransactionId = await maybeLinkTransaction(
        response.tool_calls,
        attemptedCheckouts.current,
      );
      setTurns((t) => [
        ...t,
        { role: "assistant", text: response.reply, toolCalls: response.tool_calls, linkedTransactionId },
      ]);
    } catch (err) {
      setTurns((t) => [...t, { role: "error", text: describeError(err).message }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6 sm:px-6">
        <section className="mb-6 flex flex-col gap-3 border-b border-black/10 pb-6 dark:border-white/10">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600">
            AI-native commerce
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
            Buy through AI. Safely.
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Commerce Gateway lets AI buyers discover products, prepare checkout, and
            transact within merchant-defined policies and authorization boundaries.
          </p>
          <button
            type="button"
            onClick={() => setInput(EXAMPLE_PROMPT)}
            className="mt-1 flex w-fit max-w-full items-center gap-2 rounded-md border border-black/10 bg-zinc-50 px-3 py-1.5 text-left text-xs transition-colors hover:border-black/20 hover:bg-white dark:border-white/10 dark:bg-zinc-900 dark:hover:border-white/20 dark:hover:bg-zinc-900/70"
          >
            <span className="shrink-0 font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-600">
              Try
            </span>
            <span className="truncate font-mono text-zinc-700 dark:text-zinc-300">
              &ldquo;{EXAMPLE_PROMPT}&rdquo;
            </span>
          </button>
        </section>

        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">AI Buyer</h2>
            <p className="text-sm text-zinc-500 dark:text-zinc-500">
              Describe what you want to buy. The buyer can discover products, build a
              cart, prepare checkout, and request authorization when merchant policy
              requires it.
            </p>
          </div>
          <span className="mt-0.5 flex shrink-0 items-center gap-1.5 rounded-full border border-black/10 px-2.5 py-1 text-xs dark:border-white/10">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                apiStatus === "online"
                  ? "bg-emerald-500"
                  : apiStatus === "offline"
                    ? "bg-rose-500"
                    : "bg-amber-500"
              }`}
            />
            API {apiStatus}
          </span>
        </div>

        <div
          ref={logRef}
          className="flex flex-1 flex-col gap-3 overflow-y-auto rounded-lg border border-black/10 bg-white p-4 dark:border-white/10 dark:bg-zinc-950"
          style={{ minHeight: "50vh" }}
        >
          {turns.length === 0 && (
            <p className="m-auto max-w-sm text-center text-sm text-zinc-400">
              Try: &ldquo;{EXAMPLE_PROMPT}&rdquo;
            </p>
          )}
          {turns.map((turn, index) => (
            <ChatBubble key={index} turn={turn} />
          ))}
          {sending && (
            <div className="flex items-center gap-2 self-start rounded-lg bg-zinc-100 px-3 py-2 text-sm text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-zinc-400" />
              Thinking…
            </div>
          )}
        </div>

        <form onSubmit={(event) => void handleSend(event)} className="mt-3 flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask the AI buyer to find or purchase something…"
            disabled={sending}
            className="flex-1 rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-black disabled:opacity-60 dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
          >
            Send
          </button>
        </form>
      </div>

      <HowItWorksPanel />
    </>
  );
}

/**
 * The checkout-flow integration point M6A left for callers to use
 * explicitly: if this turn's tools created a checkout, attach a
 * `Transaction` to it (`actor_type: "agent"`, since the AI buyer drove it)
 * so it shows up at `/transactions/[id]`.
 *
 * M7B recovery: if that checkout already has a transaction —
 * `transaction_already_exists`, e.g. because a retried message re-runs
 * `create_checkout` against a cart whose checkout already got linked —
 * this recovers and links the *existing* transaction instead of giving up.
 * The structured error carries `transaction_id` directly
 * (`transactionIdFromDuplicateError`); `getTransactionByCheckout` is the
 * fallback if that field is ever missing, fetching the same resource fresh
 * rather than trusting an unverified id. Only a genuinely unexpected
 * failure (network error, 5xx) still results in no link — the checkout
 * itself always remains usable either way.
 */
async function maybeLinkTransaction(
  toolCalls: ToolCallRecord[],
  attemptedCheckouts: Set<string>,
): Promise<string | undefined> {
  const checkoutCall = toolCalls.find(
    (call) => call.tool_name === "create_checkout" && call.ok && call.output,
  );
  const checkoutId = checkoutCall?.output?.id;
  if (typeof checkoutId !== "string" || attemptedCheckouts.has(checkoutId)) return undefined;

  attemptedCheckouts.add(checkoutId);
  try {
    const transaction = await createTransaction({
      checkout_id: checkoutId,
      actor_type: "agent",
      actor_id: "ai-buyer-chat",
      reason: "Checkout created via AI buyer chat.",
    });
    return transaction.id;
  } catch (err) {
    const existingId =
      transactionIdFromDuplicateError(err) ??
      (await getTransactionByCheckout(checkoutId).catch(() => null))?.id;
    return existingId ?? undefined;
  }
}

function ChatBubble({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="max-w-[85%] self-end rounded-lg bg-black px-3 py-2 text-sm text-white dark:bg-zinc-50 dark:text-black">
        {turn.text}
      </div>
    );
  }

  if (turn.role === "error") {
    return (
      <div className="max-w-[85%] self-start rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
        {turn.text}
      </div>
    );
  }

  return (
    <div className="flex max-w-[90%] flex-col gap-2 self-start rounded-lg bg-zinc-100 px-3 py-2 text-sm text-zinc-900 dark:bg-zinc-900 dark:text-zinc-100">
      <p className="whitespace-pre-wrap">{turn.text}</p>
      {turn.toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {turn.toolCalls.map((call, i) => (
            <ToolCallChip key={i} call={call} />
          ))}
        </div>
      )}
      {turn.linkedTransactionId && (
        <Link
          href={`/transactions/${turn.linkedTransactionId}`}
          className="self-start text-xs font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 dark:text-sky-400"
        >
          View transaction →
        </Link>
      )}
    </div>
  );
}

function ToolCallChip({ call }: { call: ToolCallRecord }) {
  return (
    <details className="rounded border border-black/10 bg-white text-xs dark:border-white/10 dark:bg-zinc-950">
      <summary
        className={`flex cursor-pointer select-none items-center gap-1.5 px-2 py-1 font-mono ${
          call.ok ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${call.ok ? "bg-emerald-500" : "bg-rose-500"}`} />
        {call.tool_name}
      </summary>
      <pre className="max-w-xs overflow-x-auto border-t border-black/10 p-2 font-mono text-[11px] text-zinc-600 dark:border-white/10 dark:text-zinc-400">
        {JSON.stringify(call.ok ? call.output : { error_code: call.error_code, error_message: call.error_message }, null, 2)}
      </pre>
    </details>
  );
}
