# 0001. API-first modular monolith

## Status

Accepted

## Context

Commerce Gateway needs to support a growing set of concerns that all sit on the
path of a single logical workflow: an AI buyer discovering a merchant's catalog,
building a cart, passing deterministic policy checks, obtaining authorization,
executing payment through a provider integration, and producing an audit trail.

These concerns are tightly coupled by data and by sequencing — a checkout cannot
be authorized without seeing the cart, a payment cannot be executed without a
passed policy check, and the audit trail must observe all of it consistently.
At the same time, the project is early: the exact shape of the domain (catalog
model, policy rules, state machine) is still being designed, and premature
service boundaries would need to be guessed at rather than derived from real
constraints.

We also need the frontend (Next.js) and backend (FastAPI) to evolve
independently, and we need the payment provider (initially Razorpay Test Mode)
to be swappable without touching unrelated code.

## Decision

We adopt an **API-first modular monolith**:

- A single FastAPI backend owns all domain/business logic — catalog, cart,
  checkout, policy, authorization, payment orchestration, and audit — organized
  as internal modules rather than separate services.
- The backend exposes a well-defined HTTP API. Next.js is a presentation layer
  that talks to the backend exclusively through that API — it holds no business
  logic and no direct database access.
- PostgreSQL is the single system of record.
- Payment provider integration sits behind a provider-agnostic abstraction inside
  the monolith, so Razorpay (and any future provider) is an adapter, not a
  structural assumption.
- We do not split into microservices. There is no current requirement (team
  topology, independent scaling, independent deployment cadence) that justifies
  the operational cost of distributed transactions across these tightly coupled
  concerns.

## Consequences

- Faster iteration: one deployable backend, one shared transaction boundary for
  operations that must be atomic (e.g. cart → checkout → policy check).
- Domain boundaries are enforced by internal module structure and code review
  discipline, not by network boundaries. This requires ongoing care as modules
  grow (e.g. a `policy` module must not reach into `payment` internals).
- If a concrete future requirement emerges — independent scaling of a specific
  concern, a separately deployable team boundary, or a compliance requirement
  for isolation — extracting a module into its own service is possible because
  module boundaries already exist inside the monolith. This decision does not
  preclude that; it defers it until a real requirement exists.
- The frontend/backend split is fixed early: Next.js must never encode
  business rules (pricing, policy, authorization) since that logic must remain
  deterministic and centrally auditable in the backend.
