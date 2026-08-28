# Razorpay Python SDK exposes no common exception base class

While implementing the Razorpay adapter (`app/commerce/payment/razorpay.py`)
for Milestone 5, we inspected the installed `razorpay` package (`razorpay==2.0.1`)
to confirm its exact error surface before writing exception handling:

```python
>>> import razorpay.errors as e
>>> [name for name in dir(e) if not name.startswith("_")]
['BadRequestError', 'GatewayError', 'ServerError', 'SignatureVerificationError']
>>> [cls.__mro__ for cls in (e.BadRequestError, e.GatewayError, e.ServerError)]
# each is (SomeError, Exception, BaseException, object) — no shared base
# besides the built-in Exception itself.
```

There is no `RazorpayError` (or similar) base class to catch generically —
each error type inherits directly from `Exception`. This means catching
"any Razorpay API error" requires an explicit tuple
(`BadRequestError, GatewayError, ServerError`) rather than a single except
clause, and that tuple has to be kept in sync by hand if the SDK adds error
types in a future version.

This also informed the decision (recorded in
[`docs/decisions/0007-payment-single-row-idempotency-and-provider-boundary.md`](decisions/0007-payment-single-row-idempotency-and-provider-boundary.md))
to implement payment signature verification directly with the stdlib
(`hmac`/`hashlib`) against Razorpay's publicly documented HMAC-SHA256
formula, rather than depend on `razorpay.Client().utility.verify_payment_signature`
and its `SignatureVerificationError` — the one security-critical check in
the payment domain shouldn't depend on correctly enumerating a third-party
SDK's error hierarchy.
