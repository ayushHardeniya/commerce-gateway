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
    (`max_tool_iterations`, default 4) before failing clearly rather than
    looping indefinitely. Gemini is only ever given the catalog and
    commerce tools above (`app.agents.tools.DEFAULT_TOOLS`): it has no path
    to inventory mutation, pricing, policy, authorization, or payment
    execution, because those simply are not declared tools — not because
    of a runtime permission check that could be misconfigured.
  - **API** (`agents/router.py`): `POST /api/agent/chat` — a typed
    (`AgentChatRequest`/`AgentChatResponse`) endpoint for exercising the
    loop; not a production chat UI and holds no conversation history across
    requests. Missing Gemini configuration, a Gemini/API failure, and
    iteration-limit exhaustion each surface as a distinct HTTP error
    (503/502/422) rather than a fabricated reply.
- **Frontend skeleton** (`frontend/`): a Next.js (App Router, TypeScript,
  Tailwind CSS) application with a minimal shell page that calls the backend's
  `/health` endpoint through a small API client (`src/lib/api.ts`) to confirm
  connectivity. It does not yet call the catalog API.
- **Local development infrastructure**: `docker-compose.yml` providing a
  PostgreSQL instance for local development. The backend and frontend
  applications run natively against it.
- **Configuration**: both applications read configuration from environment
  variables, with `.env.example` files documenting the expected variables. No
  secrets are committed.

## Planned (not yet implemented)

The following are part of the intended product but do not exist yet. They will
be added incrementally, each behind its own scoped change:

- **Payment execution** — a checkout that reaches `allow` or gets explicitly
  `AUTHORIZED` is eligible for payment, but nothing yet executes it. The
  remaining lifecycle steps (paid → completed, with failure/rollback paths)
  are future work built on top of the checkout/policy/authorization state
  established today.
- **Payment provider abstraction** — a provider-agnostic interface for
  executing payment, with Razorpay Test Mode as the first concrete adapter.
  The abstraction is designed so no other part of the system depends on
  Razorpay-specific behavior.
- **Audit trail** — a complete, queryable record of every step a checkout
  went through, sufficient to explain any money-moving decision after the
  fact.
- **AI buyer, beyond cart/checkout/policy** — the agent loop can discover
  products, prepare a cart/checkout, and ask what policy says about a
  checkout, but has no tool for payment because that domain doesn't exist
  yet, and no tool anywhere for granting or overriding authorization —
  that stays application-controlled by design, not merely unbuilt.
  Multi-turn conversation history across requests is also not implemented
  — each `POST /api/agent/chat` call is independent.

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
