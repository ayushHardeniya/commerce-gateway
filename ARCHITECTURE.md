# Architecture

Commerce Gateway is an API-first modular monolith. This document describes the
current system boundaries and how they are expected to evolve. See
[`docs/decisions/0001-api-first-modular-monolith.md`](docs/decisions/0001-api-first-modular-monolith.md)
for the reasoning behind that choice.

## System overview

```
┌─────────────────┐        HTTP / JSON        ┌──────────────────────┐
│  Next.js (App    │ ────────────────────────▶ │  FastAPI backend      │
│  Router) frontend │ ◀──────────────────────── │  (domain logic owner) │
└─────────────────┘                            └──────────┬───────────┘
                                                            │
                                                            ▼
                                                 ┌──────────────────────┐
                                                 │     PostgreSQL        │
                                                 └──────────────────────┘
```

- **Next.js** is the presentation layer. It renders UI and calls the backend
  over HTTP. It holds no business logic and no direct database access.
- **FastAPI** owns all domain and business logic: catalog, cart, checkout,
  policy, authorization, payment orchestration, and audit trail. It is the only
  component that talks to PostgreSQL.
- **PostgreSQL** is the single system of record.

There are no microservices. Everything on the backend runs as one deployable
FastAPI application, internally organized into modules by domain concern.

## Implemented today

- **Backend skeleton** (`backend/`): FastAPI app (`app/main.py`) with a health
  endpoint (`GET /health`), configuration via `pydantic-settings`
  (`app/core/config.py`), and a SQLAlchemy engine/session setup
  (`app/db/session.py`) with Alembic wired to the same configuration
  (`alembic/env.py`).
- **Merchant catalog module** (`app/catalog/`) — the first domain module:
  - **Models** (`models.py`): `Merchant` and `Product`, with `Product`
    belonging to exactly one `Merchant`. Money is stored as an integer count
    of the currency's minor units, never as a float — see
    [`docs/decisions/0002-money-as-integer-minor-units.md`](docs/decisions/0002-money-as-integer-minor-units.md).
    Availability (`Product.is_available`) is derived deterministically from
    stored state (`active`, `stock_quantity`, and the owning merchant's
    `active` flag) rather than tracked as separate mutable state.
  - **Migration**: `alembic/versions/` contains the migration creating the
    `merchants` and `products` tables, with foreign key, uniqueness (slug per
    merchant table, SKU per merchant), and check constraints
    (non-negative price/stock, well-formed currency code) enforced at the
    database level.
  - **Schemas** (`schemas.py`): `ProductCatalogView` is the agent-readable
    catalog representation — product identity, description, price/currency,
    availability, and embedded merchant identity in one response, so a
    consumer never needs a second lookup to evaluate a candidate product.
  - **API** (`router.py`), under `/api/catalog`: merchant-agnostic product
    search (`GET /api/catalog/products`, the AI buyer's discovery entry
    point — searches across every merchant) and the same search scoped to one
    merchant (`GET /api/catalog/merchants/{slug}/products`), both with `q`,
    `in_stock_only`, `include_inactive`, `limit`/`offset`, and a total match
    count; retrieve a single product (`GET /api/catalog/products/{id}`); and
    list/retrieve merchants (`GET /api/catalog/merchants`,
    `GET /api/catalog/merchants/{slug}`).
  - **Seed data** (`seed.py`): a small, deterministic demo catalog (two
    merchants, six products, including one out-of-stock and one inactive
    product) for local development — not used by the test suite.
- **Commerce module** (`app/commerce/`) — cart and checkout, built on top of
  the catalog. See
  [`docs/decisions/0005-cart-price-snapshot.md`](docs/decisions/0005-cart-price-snapshot.md)
  for the full reasoning; in short:
  - **Cart** (`commerce/cart/`): a `Cart` belongs to one merchant and holds
    `CartItem` line items that reference a `Product` by id rather than
    copying it. Each item snapshots `unit_price_minor_units` at add-time —
    a later catalog price change never silently changes what a cart shows.
    A cart commits to one currency (the first item's) and rejects a product
    priced in a different one. `Cart.subtotal_minor_units` is the single
    deterministic definition of a cart's total
    (`sum(unit_price_minor_units × quantity)`); nothing recomputes it
    differently elsewhere, and no LLM is ever asked to calculate or approve
    it. Availability is checked when an item is added, not on every later
    read — there is no inventory reservation.
  - **Checkout** (`commerce/checkout/`): `create_checkout` is the one place
    a cart gets revalidated against current catalog state — every product
    must still be available, and every snapshotted price must still match
    the product's current price — before a `Checkout` freezes a
    deterministic total. Either check failing returns a structured,
    listable `product_unavailable`/`price_changed` condition instead of
    silently using the new price. A `Checkout` denormalizes its own line
    items (`CheckoutItem`: product name/sku/price) independently of the
    live product row, so it stays a complete, readable record even if a
    product is later edited or deleted. `status` is `active` / `completed`
    / `cancelled` in the database; `expired` is a derived read
    (`Checkout.effective_status`) once `expires_at` has passed, the same
    computed-from-stored-state pattern as `Product.is_available` — no
    background job flips it. No payment or authorization happens anywhere
    in this module; a checkout only ever prepares for one.
  - **API**: `POST /api/carts`, `GET /api/carts/{id}`,
    `POST /api/carts/{id}/items`, `PATCH /api/carts/{id}/items/{item_id}`,
    `DELETE /api/carts/{id}/items/{item_id}`; `POST /api/checkouts`,
    `GET /api/checkouts/{id}`. Structured errors
    (`app/commerce/errors.py`) carry a machine-readable `code` (e.g.
    `cart_not_found`, `product_unavailable`, `price_changed`,
    `invalid_cart_state`) alongside a human-readable message, mapped to the
    appropriate HTTP status — the same `{code, message}` shape the agent
    tool contract already uses, not a second error framework.
  - **Dependency direction**: `app.commerce` may depend on `app.catalog`;
    nothing in `app.catalog` depends on `app.commerce`.
- **Policy and authorization module** (`app/commerce/policy/`) — the
  deterministic gate a checkout passes through before anything moves money.
  See
  [`docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`](docs/decisions/0006-policy-snapshot-and-explicit-authorization.md)
  for the full reasoning; in short:
  - **Flow**: `checkout → policy evaluation → ALLOW / REQUIRE_AUTHORIZATION /
    DENY`, and for `REQUIRE_AUTHORIZATION`, an explicit human authorization
    step produces `AUTHORIZED`. An LLM may request evaluation and read the
    result; it never decides the outcome and never grants authorization —
    both are deterministic application code, never an LLM response.
  - **`MerchantPolicy`** (`models.py`): one mutable row per merchant
    (`autonomous_limit_minor_units`, `currency`, an incrementing `version`).
    A merchant with no explicit policy gets a safe default — an autonomous
    limit of zero, so every nonzero checkout requires authorization until
    the merchant configures a higher limit — rather than unrestricted
    autonomous spending.
  - **`PolicyDecision`**: one immutable, deterministic evaluation per
    checkout (`app.commerce.policy.service.evaluate_checkout` is idempotent
    — a checkout is evaluated once, and every later call returns that same
    decision). It snapshots the exact policy values (limit, currency,
    version) it was computed against onto itself, so a merchant editing
    their policy afterward can never retroactively change what an
    already-made decision meant. The amount/currency evaluated always comes
    from the checkout's own authoritative, already-frozen total — never a
    value an LLM or any other caller supplies. Rules: an active checkout
    within the limit → `allow` (`within_autonomous_limit`); active but over
    the limit → `require_authorization` (`autonomous_limit_exceeded`); an
    expired, cancelled/completed, or currency-mismatched checkout →
    `deny`, with a matching machine-readable reason.
  - **`CheckoutAuthorization`**: the one-time human approval record for a
    `require_authorization` decision. Its existence for a checkout *is* the
    AUTHORIZED state, distinct from — and never conflated with — a future
    payment succeeding. Granting one requires the decision to actually be
    `require_authorization` (not `allow`, not `deny`), no authorization to
    already exist for that checkout, and the checkout's live
    amount/currency/status to still match both the caller's request and the
    original decision — closing the window between evaluation and a human
    approving it.
  - **API** (`router.py`), under `/api/policy`: get/upsert a merchant's
    policy (`GET`/`PUT /api/policy/merchants/{merchant_id}`), evaluate a
    checkout (`POST /api/policy/checkouts/{checkout_id}/evaluate`), read its
    decision (`GET .../decision`), authorize it
    (`POST .../authorize`), and read the authorization
    (`GET .../authorization`). Errors use the same structured `{code,
    message}` shape as cart/checkout (`app.commerce.errors`), not a second
    framework.
  - **Dependency direction**: `app.commerce.policy` may depend on
    `app.commerce.checkout`, `app.commerce.cart`, and `app.catalog`; nothing
    in those modules depends back on it.
- **Payment module** (`app/commerce/payment/`) — the deterministic gate
  between a checkout that policy has cleared and an actual Razorpay Test
  Mode charge. See
  [`docs/decisions/0007-payment-single-row-idempotency-and-provider-boundary.md`](docs/decisions/0007-payment-single-row-idempotency-and-provider-boundary.md)
  for the full reasoning; in short:
  - **Flow**: `Checkout → Policy/Authorization → Payment Service →
    PaymentProvider → Razorpay Test Mode`. Payment can never bypass policy:
    `app.commerce.payment.service` re-derives eligibility from the existing
    M4 records (a `PolicyDecision` of `allow`, or `require_authorization`
    with a matching `CheckoutAuthorization`) from scratch on every call —
    at initiation *and* again at confirmation — rather than trusting
    anything a caller claims. A `deny` decision, an expired checkout, or an
    already-paid checkout is rejected before the provider is ever called.
  - **`Payment`** (`models.py`): one row per checkout
    (`UniqueConstraint("checkout_id")`), updated in place across retries —
    the same single-mutable-row pattern `MerchantPolicy` already uses.
    `amount_minor_units`/`currency` are always copied from the checkout's
    own frozen total, never supplied by a caller; `status` is `created` /
    `success` / `failed`. A successful confirmation is the one place a
    `Checkout` transitions `active → completed`.
  - **Provider abstraction** (`provider.py`): a two-method `PaymentProvider`
    protocol (`create_order`, `verify_payment`) that
    `app.commerce.payment.service` depends on — no Razorpay-specific type
    ever appears in the service layer.
  - **Razorpay adapter** (`razorpay.py`) — the only module that imports the
    `razorpay` SDK. Creates orders through the SDK; verifies payment
    signatures with a direct stdlib HMAC-SHA256 implementation of
    Razorpay's documented scheme rather than the SDK's own verification
    helper, so the one security-critical check has no dependency on the
    SDK's internal exception hierarchy and needs no network access to test.
  - **API** (`router.py`), under `/api/checkouts/{checkout_id}/payment`:
    initiate (`POST`, no request body — amount/currency are never
    caller-supplied), confirm (`POST .../confirm`, taking Razorpay
    Checkout's own returned identifiers/signature), and read the current
    payment (`GET`). Missing Razorpay configuration surfaces as 503, a
    provider error/timeout as 502/504, an invalid signature as 409 — never
    a generic 500. Errors use the same structured `{code, message}` shape
    as the rest of `app.commerce`.
  - **Idempotency**: a checkout can have at most one successful `Payment`
    (a database constraint, not just an application check); initiating
    payment while an order is already live returns the existing order
    rather than creating a second one; confirming an already-successful
    payment again is a safe no-op that neither re-verifies the signature
    nor re-completes the checkout.
  - **Tests**: a deterministic in-memory fake `PaymentProvider`
    (`tests/commerce/payment/conftest.py`) drives all service/API tests —
    none of the suite depends on live Razorpay credentials. The Razorpay
    adapter's request/response mapping and HMAC verification are tested
    separately against a stub, still with zero network access.
  - **Dependency direction**: `app.commerce.payment` may depend on
    `app.commerce.checkout`, `app.commerce.policy`, and `app.catalog`;
    nothing in those modules depends back on it. Like `authorize_checkout`,
    nothing in `app.agents` can reach payment initiation or confirmation —
    there is no payment `Tool`, enforced by omission and backed by a
    regression test (`tests/agents/test_architecture.py`).
- **Transaction module** (`app/commerce/transaction/`) — a durable,
  business-level record of one commerce attempt as it moves across
  discovery, cart, checkout, policy, and payment, plus the deterministic
  state machine that governs it. See
  [`docs/decisions/0008-transaction-state-machine-validated-by-domain-state.md`](docs/decisions/0008-transaction-state-machine-validated-by-domain-state.md)
  for the full reasoning; in short:
  - **States** (`models.py`): `discovered → cart_created →
    checkout_created → policy_pending → authorized → payment_pending →
    payment_success → order_confirmed`, plus the failure/recovery states
    `policy_denied`, `payment_failed` (recoverable — a retried payment can
    move it back to `payment_pending`), `checkout_expired`, `cancelled`,
    and `failed`. The last four of those, plus `order_confirmed`, are
    terminal — no edge leaves them.
  - **`Transaction`** (`models.py`): one mutable row per transaction,
    updated in place — the same single-mutable-row pattern `Payment`/
    `MerchantPolicy` already use, not a per-transition history table (that
    history is `AuditEvent`, below). It references `cart_id`/`checkout_id`
    (both nullable — a transaction can exist before either is known) and
    stores no copy of cart/checkout/policy/payment data; every guarded
    transition below re-reads the real record instead.
  - **State machine** (`service.py`): a fixed table of `(from_state,
    to_state)` edges, each with a guard. An edge not in the table is
    rejected outright (`invalid_transaction_transition`, 409) — no
    skipping a state, no leaving a terminal one. For edges backed by a
    real domain fact, the guard re-reads it fresh rather than trusting the
    caller: `policy_pending → authorized` re-derives eligibility from the
    checkout's actual `PolicyDecision`/`CheckoutAuthorization` (the same
    check `app.commerce.payment.service` already performs);
    `payment_pending → payment_success`/`payment_failed` require the
    checkout's actual `Payment.status`; `→ checkout_expired` requires
    `Checkout.effective_status == "expired"`; `payment_success →
    order_confirmed` requires `Checkout.status == "completed"`. Payment
    success can never be inferred from a caller's (or an LLM's) claim —
    only a real `Payment` row moves a transaction there.
  - **Audit trail** (`models.py`/`service.py`) — see
    [`docs/decisions/0009-transaction-audit-trail-is-a-plain-append-only-table.md`](docs/decisions/0009-transaction-audit-trail-is-a-plain-append-only-table.md)
    for the full reasoning; in short: `AuditEvent` is one immutable,
    append-only row per successful transition (including the transaction's
    own creation, recorded as a transition from no previous state),
    written exclusively by `create_transaction`/`transition_transaction` —
    no router, and nothing else anywhere in the codebase, writes one.
    Ordering is a database-generated `sequence` identity column, not
    `created_at` or the row's UUID (neither is a reliable order). Each row
    records `from_state`/`to_state`, `actor_type` (`system` or `agent` —
    a caller-stated distinction, not an authenticated one; every
    transition today is `system` since no `Tool` in `app.agents` reaches
    this module) and an optional `actor_id`, a `reason` (a domain-derived
    fact — a policy denial reason, a payment failure code — when a guard
    produced one, otherwise whatever the caller supplied), and small
    `event_metadata` (policy decision id, payment id, and similar — never
    a copy of the checkout/payment/catalog record those ids point to). A
    transition rejected by the state machine never produces an event: the
    guard raises before either the `Transaction` mutation or the
    `AuditEvent` insert happens. The `Transaction` row's own mutation and
    its `AuditEvent` are added to the session together and flushed/
    committed in one call, so a transition and the record that it happened
    are persisted atomically with no distributed-transaction machinery.
  - **API** (`router.py`), under `/api/transactions`: create
    (`POST`, optionally anchored to an existing `checkout_id` — the one
    checkout-flow integration point, starting the transaction directly at
    `checkout_created` with no change needed to `app.commerce.checkout`
    itself), read (`GET /{id}`), a plain newest-first paginated listing
    (`GET`, `limit`/`offset` only — ordered by a database-generated
    `Transaction.sequence` identity column, the same reasoning
    `AuditEvent.sequence` already documents: `created_at` alone isn't a
    reliable order for rows inserted in the same DB transaction), lookup by
    checkout (`GET /by-checkout/{checkout_id}`, M7B — the recovery path for
    a caller that only has a checkout id, e.g. after a duplicate-creation
    conflict), the single guarded transition endpoint
    (`POST /{id}/transitions`), and the read-only audit history
    (`GET /{id}/audit-events`, ordered oldest-first by `sequence`). Errors
    use the same structured `{code, message}` shape as the rest of
    `app.commerce`; creating a transaction for a checkout that already has
    one returns `409 transaction_already_exists` with the existing
    `transaction_id` in the body, so a caller can recover it rather than
    just detect the conflict.
  - **Dependency direction**: `app.commerce.transaction` may depend on
    `app.commerce.cart`, `app.commerce.checkout`, `app.commerce.policy`,
    and `app.commerce.payment`; nothing in those modules depends back on
    it. No `Tool` in `app.agents` can reach transaction creation,
    transitions, or audit retrieval — enforced by omission and backed by a
    regression test (`tests/agents/test_architecture.py`), the same
    pattern already used for payment.
- **Agent tool layer** (`app/agents/`) — the structured interface a future AI
  buyer will act through. See
  [`docs/decisions/0004-agent-tool-contract.md`](docs/decisions/0004-agent-tool-contract.md)
  for the full reasoning; in short:
  - **Contract** (`agents/tools/base.py`): a provider-neutral `Tool` base
    class — explicit `name`/`description`, a typed Pydantic input schema, a
    typed output schema, and a single `run()` entry point that validates
    input, executes deterministically, and always returns a structured
    `ToolResult` (`output` or a typed `ToolError` with a closed
    `ToolErrorCode` — `invalid_input` / `not_found` / `internal_error`).
    `run()` never raises, and no vendor SDK is referenced anywhere in this
    layer.
  - **Catalog tools** (`agents/tools/catalog.py`): `search_catalog` and
    `get_product`, thin deterministic wrappers over
    `app.catalog.repository` (the same functions the HTTP API calls) —
    reusing `ProductCatalogView`/`ProductPage` as their output, so the agent
    and the HTTP API can never see different availability/filtering
    semantics. No HTTP calls back into our own API, no ranking or semantic
    search, no LLM calls inside a tool.
  - **Commerce tools** (`agents/tools/commerce.py`): `create_cart`,
    `get_cart`, `add_cart_item`, `update_cart_item_quantity`,
    `remove_cart_item`, `create_checkout` — each a thin wrapper over
    `app.commerce.cart.service` / `app.commerce.checkout.service`, the same
    functions the HTTP API calls. A tool never computes a total, decides a
    price, or touches a repository/database directly; every business rule
    (availability, price-snapshot revalidation, deterministic totals) lives
    in those services.
  - **Policy tool** (`agents/tools/policy.py`): exactly one capability,
    `evaluate_checkout_policy` — a thin wrapper over
    `app.commerce.policy.service.evaluate_checkout` that lets Gemini ask
    what policy says about an existing checkout and read back
    `allow`/`require_authorization`/`deny` plus its reason. It cannot
    supply its own amount (the service always loads the checkout's
    authoritative total), change a merchant's policy, override a decision,
    or grant authorization — there is no tool for any of that, and no
    `Tool` in `app.agents` can reach `authorize_checkout`, which is only
    ever called from `app.commerce.policy.router` (HTTP). Gemini has no
    tool for payment because it doesn't exist yet — enforced by omission,
    not a runtime check.
  - **Dependency direction**: `app.agents` may depend on `app.catalog` and
    `app.commerce`; nothing in `app.catalog` or `app.commerce` may depend on
    `app.agents`. This is enforced by a static import check in
    `backend/tests/agents/test_architecture.py`, not just convention.
  - **Gemini adapter** (`agents/gemini_client.py`) — the only file that
    imports `google.genai`. Builds a configured client from
    `GEMINI_API_KEY`/`GEMINI_MODEL` (`app/core/config.py`) and translates
    each `Tool`'s Pydantic input schema into Gemini's native
    function-declaration format. Gemini is the current AI reasoning
    component; nothing outside this one module is Gemini-specific.
  - **Agent loop** (`agents/buyer.py`, `AIBuyerService`): accepts one user
    message, sends it to Gemini together with the declared catalog tools,
    and on each function call Gemini proposes, validates and executes it
    through the `Tool` contract and returns the structured result to Gemini
    — repeating for at most a small, fixed number of model turns
    (`max_tool_iterations`, default 6) before failing clearly rather than
    looping indefinitely. Gemini is only ever given the catalog and
    commerce tools above (`app.agents.tools.DEFAULT_TOOLS`): it has no path
    to inventory mutation, pricing, policy, authorization, or payment
    execution, because those simply are not declared tools — not because
    of a runtime permission check that could be misconfigured. Every
    request also carries a fixed `system_instruction`
    (`CURRENCY_SAFETY_INSTRUCTION`, M7B): the catalog only ever prices in
    USD, and there is no FX service anywhere in this codebase, so the model
    is explicitly told never to convert a user-stated budget in another
    currency (e.g. INR) itself or claim such a budget is satisfied/exceeded
    from its own estimate — only to flag the mismatch and ask the user to
    restate it in USD. This is a prompt-level guardrail, not a code-level
    check, because the mismatch only ever exists in the user's free-text
    message.
  - **API** (`agents/router.py`): `POST /api/agent/chat` — a typed
    (`AgentChatRequest`/`AgentChatResponse`) endpoint for exercising the
    loop; not a production chat UI and holds no conversation history across
    requests. Missing Gemini configuration, a Gemini/API failure, and
    iteration-limit exhaustion each surface as a distinct HTTP error
    (503/502/422) rather than a fabricated reply.
- **Frontend** (`frontend/`) — a Next.js (App Router, TypeScript, Tailwind
  CSS) application. It holds no business logic and computes no authoritative
  value (price, policy decision, payment amount, transaction state) itself;
  every page is a thin view over `app/main.py`'s API, reachable only through
  `src/lib/api/` (`src/lib/api.ts` re-exported as a barrel — nothing outside
  it calls `fetch` against `NEXT_PUBLIC_API_BASE_URL` directly), split into
  one file per backend domain (`catalog.ts`, `checkout.ts`, `policy.ts`,
  `payment.ts`, `transaction.ts`, `agent.ts`) mirroring `app/commerce/<domain>/schemas.py`.
  Routes:
  - `/` — the AI buyer surface: a chat UI over `POST /api/agent/chat`. Each
    message is one independent request (the backend holds no conversation
    history — see the agent loop above); the UI shows the reply alongside
    the deterministic tool-call trace behind it (name, arguments, ok/error,
    output), not just the model's prose. When a turn's tools created a
    checkout, the page calls `POST /api/transactions` with that
    `checkout_id` (`actor_type: "agent"`) — the M6A checkout-flow
    integration point — and links to that transaction's detail page. If
    that checkout already has one (`409 transaction_already_exists`, M7B),
    the page recovers it instead of giving up: it reads the id straight off
    the structured error, falling back to `GET /api/transactions/by-checkout/{id}`
    if that field is ever missing, so the conversation always ends with a
    working transaction link rather than a dead end.
  - `/transactions/[id]` — reads `GET /api/transactions/{id}`,
    `GET /api/transactions/{id}/audit-events`, and, once a `checkout_id` is
    known, `GET /api/checkouts/{id}`, `GET /api/checkouts/{id}/payment`, and
    `GET /api/policy/checkouts/{id}/decision` to show identity, current
    state, checkout/payment/policy summaries, and the full audit trail. Its
    state-progression view renders exactly the path in the audit trail
    (one node per `AuditEvent.to_state`, in `sequence` order) rather than a
    frontend copy of the transaction FSM — the page has no knowledge of
    which transitions are valid, only of what the backend already recorded.
    Read-only in M7A: no transition actions from the UI yet.
  - `/merchant` — a merchant picker (from `GET /api/catalog/merchants`, no
    auth/session concept exists) plus, per merchant: identity, its catalog
    (`GET /api/catalog/merchants/{slug}/products`, searchable/paginated),
    and its autonomous policy (`GET`/`PUT /api/policy/merchants/{id}`) via
    a form that submits whatever limit/currency the operator chose — the
    backend still owns whether it's accepted.
  - `/pay` — unchanged from M5/M6: the Razorpay Test Mode Checkout
    integration boundary. `/transactions/[id]` links into it
    (`/pay?checkout_id=...`) as a query-param prefill only; the payment
    flow itself was not touched.
  - There is no "list transactions" or "list transactions for a merchant"
    endpoint (M6B only added create/get/transition/audit-events for one
    transaction at a time), so `/transactions/[id]` is reached either from
    the AI buyer flow's own link or a direct id lookup (a small form in the
    top nav) — not a browsable list.
- **Local development infrastructure**: `docker-compose.yml` providing a
  PostgreSQL instance for local development. The backend and frontend
  applications run natively against it.
- **Configuration**: both applications read configuration from environment
  variables, with `.env.example` files documenting the expected variables. No
  secrets are committed.

## Planned (not yet implemented)

The following are part of the intended product but do not exist yet. They will
be added incrementally, each behind its own scoped change:

- **Reconciliation** — M6B's `AuditEvent` trail (see above) records every
  successful `Transaction` transition, but nothing yet reconciles a
  provider-side event (e.g. a Razorpay success) that arrives after a
  checkout has already expired, or replays/repairs a transaction stuck
  behind a `payment_failed` state without a caller-driven retry.
- **Payment webhooks** — M5's confirmation path is the synchronous
  Checkout.js round-trip (order → widget → `razorpay_payment_id`/
  `razorpay_signature` → server verification). Asynchronous/delayed payment
  methods and reconciliation via Razorpay webhooks are not implemented.
- **Refunds** — no refund capability exists in the payment provider
  abstraction or the API.
- **Checkout/payment-attempt-level audit trail** — M6B's `AuditEvent` covers
  every `Transaction` state transition, but not a separate, finer-grained
  history of every individual payment attempt (only the current one is
  persisted — see `Payment`'s single-mutable-row design) or of
  checkout/cart edits below the transaction level.
- **AI buyer, beyond cart/checkout/policy** — the agent loop can discover
  products, prepare a cart/checkout, and ask what policy says about a
  checkout, but has no tool for payment, and no tool anywhere for granting
  or overriding authorization — that stays application-controlled by
  design, not merely unbuilt. Multi-turn conversation history across
  requests is also not implemented — each `POST /api/agent/chat` call is
  independent.

## Determinism boundary

This boundary is a hard architectural constraint, not a style preference:
financial calculations, authorization decisions, policy enforcement,
transaction state transitions, idempotency, and payment execution must be
deterministic and must never depend on an LLM's output. AI is used only where
reasoning over natural language adds genuine value (e.g. interpreting a
shopping request or narrowing catalog search) — never inside the code path that
moves money or changes transaction state. Every money-moving action must be
explainable, bounded, gated, and auditable.

## Evolution path

The module boundaries inside the FastAPI backend (catalog, cart/checkout,
policy, payment, audit) are drawn so that a module could be extracted into a
separately deployable service later, if a concrete requirement (independent
scaling, independent deployment cadence, team/compliance isolation) emerges.
No such requirement exists today, so the system remains a single deployable
monolith.
