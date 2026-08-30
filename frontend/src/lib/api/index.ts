/**
 * The frontend's one API boundary. Every backend call in this app goes
 * through a function exported from `src/lib/api/*` — nothing outside this
 * directory calls `fetch` against `NEXT_PUBLIC_API_BASE_URL` directly. This
 * barrel is what the rest of the app imports (`@/lib/api`); the domain
 * split (`catalog.ts`, `checkout.ts`, `policy.ts`, `payment.ts`,
 * `transaction.ts`, `agent.ts`) exists only to keep each file focused on one
 * backend module, mirroring `app/commerce/<domain>/schemas.py` on the
 * backend one-for-one.
 */

export * from "./client";
export * from "./catalog";
export * from "./cart";
export * from "./checkout";
export * from "./policy";
export * from "./payment";
export * from "./transaction";
export * from "./agent";
