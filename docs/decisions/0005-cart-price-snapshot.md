# 0005. Cart items snapshot price; checkout revalidates and freezes it

## Status

Accepted

## Context

Milestone 3 introduces the first mutable, money-relevant state that outlives
a single request: a cart can sit around — being built up, put down, and
picked back up — while a merchant's product catalog keeps changing
underneath it (`docs/decisions/0002-money-as-integer-minor-units.md`
established that prices themselves are exact integers; this decision is
about what happens when the *catalog's* price for a product moves after a
customer has already put that product in a cart).

Three related questions had to be answered before cart/checkout could be
built at all:

1. If a product's price changes, or the product goes out of stock or
   inactive, after it's already in someone's cart, what does the cart show?
2. A cart belongs to one merchant, but nothing in the catalog schema
   guarantees every product a merchant sells shares one currency — what
   happens if a cart's items don't agree on currency?
3. A checkout is meant to be the durable, auditable record of "what was
   this customer about to buy" — but products (and even merchants) can be
   edited or deleted after a checkout is created. How does a checkout stay
   meaningful once that happens?

## Decision

**Cart items snapshot the unit price at add-time; checkout is the
revalidation point, not the cart.** `CartItem.unit_price_minor_units` is set
once, when the item is added, and is never silently rewritten by a later
catalog price change — the cart always shows the price the customer actually
saw. Availability and quantity are validated when an item is *added*, not
on every later read or quantity update; there is no inventory reservation
(a cart holding an item does not lock stock for anyone else).

**`create_checkout` is the one place a cart's snapshot gets checked against
current catalog state**, in a fixed order: verify every product is still
available, then verify every snapshotted price still matches the product's
current price. If either check fails, checkout creation is rejected with a
structured `product_unavailable` or `price_changed` error (listing every
affected line item, not just the first) — the payable total is never
silently recalculated to the new price. The customer (or the AI buyer
acting for them) has to act again — update the cart, remove the item, or
retry — with full knowledge of what changed, deterministically, with no
LLM involved in that decision.

**A cart commits to one currency**, taken from the first item added; adding
a product priced in a different currency is rejected
(`currency_mismatch`) rather than silently summed across currencies. This
keeps `subtotal_minor_units = sum(unit_price_minor_units × quantity)` always
meaningful — there is never a mix of currencies to add together by mistake.

**A checkout snapshots its line items independently of the cart and the
live product row** (`CheckoutItem.product_name` / `product_sku` /
`unit_price_minor_units`, alongside a nullable, `ON DELETE SET NULL`
foreign key to the product). This is the direct, concrete case
`docs/decisions/0003-merchant-deletion-cascades-to-products.md` flagged in
advance: now that a durable commerce record (`checkouts`) references
products, a product being edited or deleted must not corrupt or silently
alter that record. `Checkout.cart_id` is `ON DELETE RESTRICT` for the same
reason — deleting a cart's merchant (still a hard-delete cascade per ADR
0003) now fails loudly if any of that merchant's carts has a checkout,
rather than quietly destroying it. `CartItem.product_id`, by contrast, stays
`ON DELETE CASCADE`: a cart is still pre-purchase, ephemeral state, so if a
product is deleted there is nothing left to add to a cart for.

## Consequences

- An AI buyer (or any client) can always trust that a cart's displayed
  total matches the prices the customer actually agreed to when adding each
  item — and that checkout will only ever freeze a total the customer has
  had a chance to review at current prices, never a stale one.
- `price_changed` / `product_unavailable` are permanent, real states a
  checkout attempt can land in — they are not transient errors to retry
  blindly. A caller must re-fetch the cart, decide what to do, and try
  again.
- This does not implement inventory reservation: two carts can both hold
  the last unit of a product, and both can pass checkout's availability
  check if stock allows it at that instant. That remains out of scope for
  this milestone, as instructed, and would need its own design once payment
  execution exists.
- `CheckoutStatus.EXPIRED` is a derived read (`Checkout.effective_status`),
  never a value written to the `status` column — the same
  computed-from-stored-state pattern `Product.is_available` already
  established. No background job is needed to "expire" a checkout.
