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
  - **Dependency direction**: `app.agents` may depend on `app.catalog`;
    nothing in `app.catalog` (or any other domain module) may depend on
    `app.agents`. This is enforced by a static import check in
    `backend/tests/agents/test_architecture.py`, not just convention.
  - Not yet built: the agent loop that actually calls an LLM with these
    tools, and any provider adapter (Gemini or otherwise) — see "Planned"
    below.
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

- **Cart and checkout workflow** — cart creation and checkout initiation as
  explicit, auditable state.
- **Transaction state machine** — deterministic modeling of a transaction's
  lifecycle (created → policy-checked → authorized → paid → completed, with
  failure/rollback paths).
- **Policy engine** — deterministic, non-LLM checks that gate a transaction
  before authorization (e.g. spend limits, allowed merchants/categories).
- **Authorization** — the mechanism by which a transaction is explicitly
  approved before payment execution.
- **Payment provider abstraction** — a provider-agnostic interface for
  executing payment, with Razorpay Test Mode as the first concrete adapter.
  The abstraction is designed so no other part of the system depends on
  Razorpay-specific behavior.
- **Audit trail** — a complete, queryable record of every step a transaction
  went through, sufficient to explain any money-moving decision after the
  fact.
- **AI buyer agent** — the conversational loop that understands a
  natural-language shopping request and calls the tools in `app/agents/tools`
  (and future cart/checkout tools) to act on it, plus a concrete LLM provider
  adapter (e.g. Gemini) behind the provider-neutral tool contract described
  above.

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
