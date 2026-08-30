/**
 * Shared HTTP plumbing for every domain module under `src/lib/api/`. This is
 * the one place a base URL, error shape, or fetch convention is defined —
 * domain modules (`catalog.ts`, `transaction.ts`, ...) only ever build on
 * top of this, never call `fetch` directly. That keeps `src/lib/api/` the
 * single boundary between the frontend and the backend, per
 * `NEXT_PUBLIC_API_BASE_URL` / `src/lib/api.ts` in `CLAUDE.md`.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Structured `{code, message, ...}` error shape every commerce endpoint
 * returns (see `app.commerce.errors.CommerceError.detail()` on the
 * backend) — surfaced as a typed error instead of a generic HTTP failure so
 * the UI can show what actually went wrong (e.g. `invalid_payment_signature`,
 * `authorization_required`), and so callers can branch on `code` (e.g. treat
 * `*_not_found` as an empty state rather than a hard error).
 *
 * Some error codes carry extra fields beyond `code`/`message` — e.g.
 * `transaction_already_exists` carries `transaction_id` (see
 * `CheckoutAlreadyHasTransactionError.detail()`). `detail` is the raw parsed
 * body so a caller that knows a code's shape can read those fields; nothing
 * generic here tries to interpret them.
 */
export class ApiError extends Error {
  code: string;
  status: number;
  detail: Record<string, unknown>;

  constructor(code: string, message: string, status: number, detail: Record<string, unknown>) {
    super(message);
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

export async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    if (detail?.code) {
      throw new ApiError(detail.code, detail.message ?? "Request failed.", response.status, detail);
    }
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  return parseOrThrow<T>(response);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return parseOrThrow<T>(response);
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseOrThrow<T>(response);
}

/** True when `err` is an `ApiError` whose backend `code` is one of `codes`
 * — the standard way a page distinguishes "this resource genuinely doesn't
 * exist yet" (an empty state) from a real failure. */
export function isApiErrorCode(err: unknown, ...codes: string[]): err is ApiError {
  return err instanceof ApiError && codes.includes(err.code);
}
