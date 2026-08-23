# 0003. Merchant deletion hard-deletes its products via database cascade

## Status

Accepted

## Context

`products.merchant_id` is a foreign key to `merchants.id` declared with
`ON DELETE CASCADE` (see the initial migration and
`app/catalog/models.py`). Deleting a `Merchant` row therefore deletes every
`Product` row that belongs to it, enforced by PostgreSQL itself rather than
by application code.

At this milestone, `Merchant` and `Product` are the only durable entities in
the system. Nothing else references a `Product` row, so a merchant's catalog
being removed along with the merchant has no effect outside the catalog
module itself.

## Decision

For the catalog milestone, merchant deletion remains a hard delete that
cascades to products at the database level. No soft-delete, restrict, or
archival behavior is introduced yet.

This is an explicit, scoped trade-off, not a long-term data-retention policy:

- **Acceptable now**: the only thing a deleted product could "orphan" is
  itself — there are no carts, orders, or transactions that hold a reference
  to a `Product` row.
- **Must be reconsidered before any durable commerce record references a
  product.** Once carts, orders, transactions, or audit records store a
  `product_id` (or a snapshot derived from one), an unrestricted
  `ON DELETE CASCADE` on `products` (or a cascade from `merchants` through
  `products`) would silently destroy or dangle those records as a side effect
  of catalog cleanup — which conflicts with this project's requirement that
  every money-moving action be auditable after the fact
  (`CLAUDE.md`, `ARCHITECTURE.md`).

## Consequences

- Catalog cleanup (removing a test/demo merchant, or a merchant closing their
  storefront) is simple today: one `DELETE FROM merchants WHERE ...` removes
  the merchant and its products consistently, with no orphaned rows possible.
- Before any future milestone introduces a durable entity that references
  `products.id` (cart line items, order line items, transaction records),
  that work must revisit this decision — likely replacing the cascade with
  one or more of: soft-delete (`Product`/`Merchant` marked inactive rather
  than removed), `ON DELETE RESTRICT` on the referencing table, or storing an
  immutable snapshot of the product at reference time rather than a live
  foreign key. Which approach is right depends on the shape of that future
  schema, so it is deliberately not decided here.
- This ADR does not change the schema — it documents the trade-off already
  encoded in the initial migration so it isn't rediscovered by accident once
  the stakes are higher.
