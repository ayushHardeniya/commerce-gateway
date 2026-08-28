"use client";

import { useState } from "react";
import { ApiError, confirmPayment, initiatePayment } from "@/lib/api";

/**
 * The minimum Razorpay Test Mode payment surface needed to exercise the
 * real M5 flow end to end: initiate payment against our backend, open
 * Razorpay's own Standard Checkout widget, and hand its result back to the
 * backend for server-side verification. This page never decides whether a
 * payment is authorized or succeeded — it only relays Razorpay's response;
 * the backend (`app.commerce.payment.service`) is authoritative. Not a
 * production checkout UI: no cart browsing, no styling system, just enough
 * to drive and observe a real Test Mode payment.
 */

const RAZORPAY_CHECKOUT_SCRIPT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

type RazorpaySuccessResponse = {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description: string;
  handler: (response: RazorpaySuccessResponse) => void;
  modal?: { ondismiss?: () => void };
};

type RazorpayCheckout = { open: () => void };

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayCheckout;
  }
}

function loadRazorpayScript(): Promise<void> {
  if (window.Razorpay) {
    return Promise.resolve();
  }
  const existing = document.querySelector<HTMLScriptElement>(
    `script[src="${RAZORPAY_CHECKOUT_SCRIPT_SRC}"]`,
  );
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Failed to load Razorpay.")));
    });
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_CHECKOUT_SCRIPT_SRC;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay Checkout."));
    document.body.appendChild(script);
  });
}

type Stage = "idle" | "initiating" | "awaiting_checkout" | "confirming" | "success" | "error";

export default function PayPage() {
  const [checkoutId, setCheckoutId] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handlePay() {
    if (!checkoutId.trim()) {
      setStage("error");
      setMessage("Enter a checkout id.");
      return;
    }

    setStage("initiating");
    setMessage(null);

    let order;
    try {
      order = await initiatePayment(checkoutId.trim());
    } catch (err) {
      setStage("error");
      setMessage(describeError(err));
      return;
    }

    try {
      await loadRazorpayScript();
    } catch (err) {
      setStage("error");
      setMessage(describeError(err));
      return;
    }

    setStage("awaiting_checkout");

    const razorpay = new window.Razorpay!({
      key: order.razorpay_key_id,
      amount: order.amount_minor_units,
      currency: order.currency,
      order_id: order.provider_order_id,
      name: "Commerce Gateway (Test Mode)",
      description: `Checkout ${order.checkout_id}`,
      handler: (response) => {
        void (async () => {
          setStage("confirming");
          try {
            const payment = await confirmPayment(order.checkout_id, {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            setStage("success");
            setMessage(`Payment ${payment.status}. Checkout completed.`);
          } catch (err) {
            setStage("error");
            setMessage(describeError(err));
          }
        })();
      },
      modal: {
        ondismiss: () => {
          setStage((current) => (current === "awaiting_checkout" ? "idle" : current));
        },
      },
    });
    razorpay.open();
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-zinc-50 px-6 font-sans dark:bg-black">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Pay a checkout (Razorpay Test Mode)
        </h1>
        <p className="max-w-md text-sm text-zinc-600 dark:text-zinc-400">
          For an ALLOW or authorized checkout only. The backend decides
          eligibility and verifies the payment server-side — this page just
          relays Razorpay&apos;s result.
        </p>
      </div>

      <div className="flex w-full max-w-sm flex-col gap-3">
        <input
          type="text"
          value={checkoutId}
          onChange={(event) => setCheckoutId(event.target.value)}
          placeholder="Checkout id"
          className="rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-black dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="button"
          onClick={() => void handlePay()}
          disabled={stage === "initiating" || stage === "awaiting_checkout" || stage === "confirming"}
          className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
        >
          {stage === "initiating"
            ? "Creating order…"
            : stage === "awaiting_checkout"
              ? "Waiting for Razorpay…"
              : stage === "confirming"
                ? "Verifying payment…"
                : "Pay"}
        </button>
      </div>

      {message && (
        <p
          className={`max-w-sm text-center text-sm ${
            stage === "success"
              ? "text-green-600 dark:text-green-400"
              : stage === "error"
                ? "text-red-600 dark:text-red-400"
                : "text-zinc-600 dark:text-zinc-400"
          }`}
        >
          {message}
        </p>
      )}
    </div>
  );
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.code}: ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Something went wrong.";
}
