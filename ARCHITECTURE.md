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
  (`alembic/env.py`). No domain models or migrations exist yet.
- **Frontend skeleton** (`frontend/`): a Next.js (App Router, TypeScript,
  Tailwind CSS) application with a minimal shell page that calls the backend's
  `/health` endpoint through a small API client (`src/lib/api.ts`) to confirm
  connectivity.
- **Local development infrastructure**: `docker-compose.yml` providing a
  PostgreSQL instance for local development. The backend and frontend
  applications run natively against it.
- **Configuration**: both applications read configuration from environment
  variables, with `.env.example` files documenting the expected variables. No
  secrets are committed.

## Planned (not yet implemented)

The following are part of the intended product but do not exist yet. They will
be added incrementally, each behind its own scoped change:

- **Merchant catalog module** — structured product discovery interface that an
  AI buyer can query.
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
- **AI buyer agent** — natural-language request understanding and product
  selection reasoning, implemented with an LLM using structured tool/function
  calling against the catalog and cart APIs.

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
