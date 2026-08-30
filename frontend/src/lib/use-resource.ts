"use client";

/**
 * A small shared data-fetching hook — not a state-management library, just
 * the loading/empty/error bookkeeping every page in this app needs when it
 * calls `src/lib/api`. Centralizing it here means every page treats a
 * "not found yet" backend response (e.g. no payment initiated, no policy
 * configured) as an explicit empty state rather than an error banner,
 * consistently.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { isApiErrorCode } from "@/lib/api";

export type Resource<T> =
  | { status: "loading" }
  | { status: "loaded"; data: T }
  | { status: "empty" }
  | { status: "error"; error: unknown };

type UseResourceOptions = {
  /** ApiError codes that mean "nothing here yet" rather than a real
   * failure — e.g. `payment_not_found` before a payment has been
   * initiated. Rendered as an empty state, not an error banner. */
  emptyCodes?: string[];
  /** Skip fetching entirely (e.g. a prerequisite id isn't known yet). */
  skip?: boolean;
};

export function useResource<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  options?: UseResourceOptions,
): Resource<T> & { reload: () => void; silentReload: () => void } {
  const [resource, setResource] = useState<Resource<T>>({ status: "loading" });
  const [tick, setTick] = useState(0);
  const skip = options?.skip ?? false;
  // Set by `silentReload` just before it bumps `tick`, consumed once by the
  // effect below — lets a background refresh (polling) update the data in
  // place without flashing the UI back to a loading state first, while a
  // normal `reload()` (e.g. a "Refresh" button) still shows one.
  const silentRef = useRef(false);

  useEffect(() => {
    // Skipping is a render-time decision (see the early return below) —
    // the effect just doesn't fetch, rather than setting state to reflect
    // it, so there's nothing to synchronize here for that case.
    if (skip) {
      silentRef.current = false;
      return;
    }

    let cancelled = false;
    const isSilent = silentRef.current;
    silentRef.current = false;

    if (!isSilent) {
      setResource({ status: "loading" });
    }

    fetcher()
      .then((data) => {
        if (!cancelled) setResource({ status: "loaded", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (options?.emptyCodes && isApiErrorCode(error, ...options.emptyCodes)) {
          setResource({ status: "empty" });
        } else {
          setResource({ status: "error", error });
        }
      });

    return () => {
      cancelled = true;
    };
    // `deps` is caller-supplied on purpose — this hook is generic over any
    // fetcher, so the dependency list can't be statically verified here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, skip]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const silentReload = useCallback(() => {
    silentRef.current = true;
    setTick((t) => t + 1);
  }, []);

  if (skip) {
    return { status: "empty", reload, silentReload };
  }

  return { ...resource, reload, silentReload };
}

/**
 * Lightweight polling: calls `callback` every `intervalMs` while `enabled`
 * is true, and stops (clears the interval) the instant `enabled` goes
 * false or the component unmounts — no new backend infrastructure, no
 * WebSockets/SSE, just a plain interval. `enabled` is meant to be derived
 * fresh each render (e.g. "transaction isn't in a terminal state yet"), so
 * a state transition into a terminal outcome naturally stops the polling
 * on the next render.
 */
export function usePolling(
  callback: () => void,
  { intervalMs, enabled }: { intervalMs: number; enabled: boolean },
): void {
  const callbackRef = useRef(callback);
  useEffect(() => {
    callbackRef.current = callback;
  });

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => callbackRef.current(), intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs]);
}
