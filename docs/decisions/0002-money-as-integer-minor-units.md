# 0002. Represent money as integer minor units

## Status

Accepted

## Context

The catalog domain introduces the first persisted money value in the system:
`Product.price`. Every later milestone (cart totals, policy spend limits,
payment execution, refunds) builds on top of whatever representation is
chosen here, so getting it wrong is expensive to unwind later.

Floating-point types (Python `float`, SQL `float`/`double precision`) cannot
represent most decimal fractions exactly (`0.1 + 0.2 != 0.3` in binary
floating point). For money, that means totals, comparisons, and stored values
can silently drift from the "real" amount — unacceptable for a system whose
own conventions (`CLAUDE.md`, `ARCHITECTURE.md`) require every money-moving
action to be deterministic and exactly explainable.

## Decision

Money is stored as an integer count of the currency's smallest unit ("minor
units") — e.g. cents for USD, paise for INR — rather than as a float or a
decimal type:

- `Product.price_minor_units` is a `BigInteger`, constrained `>= 0`.
- `Product.currency` is a fixed 3-character ISO 4217 code, constrained to
  uppercase.
- The API exposes `price_minor_units` and `currency` as separate fields. No
  endpoint converts this to a floating-point decimal amount; any human-facing
  formatting is a presentation-layer concern, not something the domain layer
  produces or stores.

This mirrors how most payment providers (including Razorpay, the project's
first payment integration target) represent amounts in their own APIs, so no
lossy conversion will be needed at the payment integration boundary either.

## Consequences

- Arithmetic on prices (sums, comparisons, multiplication by quantity) is
  exact integer arithmetic — no rounding error can be introduced by storage
  or transport.
- This milestone does not yet handle currencies whose minor unit is not
  1/100th of the major unit (e.g. JPY, which has no minor unit, or BHD, which
  has three decimal places). The `price_minor_units` column is correct
  regardless — it always means "the number of minor units of `currency`" —
  but no unit-conversion or display-formatting logic exists yet. That must be
  added deliberately (with a currency → minor-unit-exponent table) before the
  catalog seeds or accepts a currency with a non-standard exponent.
- Every future money field in the system (cart totals, transaction amounts,
  policy spend limits, refund amounts) should follow the same
  integer-minor-units convention for consistency.
