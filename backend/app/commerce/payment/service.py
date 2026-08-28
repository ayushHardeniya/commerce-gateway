"""Payment business rules: the deterministic gate between a checkout that is
ALLOW/AUTHORIZED and an actual Razorpay Test Mode charge.

Nothing here ever asks an LLM whether a payment should happen, and nothing
here ever trusts a caller-supplied amount or currency — both always come
from the checkout's own frozen total (`Checkout.total_minor_units`/
`currency`), the same discipline `app.commerce.policy.service` already
applies. `_load_payable_checkout`/`_ensure_policy_eligible` re-derive
eligibility from scratch on every call — at initiation *and* again at
confirmation — mirroring `authorize_checkout`'s re-check of live checkout
state between evaluation and approval (see
`docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`).

`initiate_payment` never calls the provider until eligibility has already
passed: a denied/unauthorized/expired checkout never reaches Razorpay at
all, not even to create an order.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.commerce.checkout import repository as checkout_repository
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    AuthorizationInvalidError,
    AuthorizationRequiredError,
    CheckoutAlreadyPaidError,
    CheckoutExpiredError,
    CheckoutInvalidError,
    CheckoutNotFoundError,
    CommerceError,
    InvalidPaymentSignatureError,
    InvalidPaymentStateError,
    PaymentNotFoundError,
    PolicyDecisionNotFoundError,
    PolicyDeniedError,
)
from app.commerce.errors import PaymentProviderError as CommercePaymentProviderError
from app.commerce.errors import PaymentProviderTimeoutError as CommercePaymentProviderTimeoutError
from app.commerce.payment import repository as payment_repository
from app.commerce.payment.models import Payment
from app.commerce.payment.provider import PaymentProvider, ProviderError, ProviderTimeoutError
from app.commerce.policy import repository as policy_repository
from app.commerce.policy.service import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_REQUIRE_AUTHORIZATION,
)

PROVIDER_NAME = "razorpay"

STATUS_CREATED = "created"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


def _load_payable_checkout(db: Session, checkout_id: uuid.UUID) -> Checkout:
    checkout = checkout_repository.get_checkout_by_id(db, checkout_id)
    if checkout is None:
        raise CheckoutNotFoundError(f"No checkout found with id '{checkout_id}'.")

    effective_status = checkout.effective_status
    if effective_status == "expired":
        raise CheckoutExpiredError(f"Checkout '{checkout_id}' has expired.")
    if effective_status == "completed":
        raise CheckoutAlreadyPaidError(f"Checkout '{checkout_id}' has already been paid.")
    if effective_status != "active":
        raise CheckoutInvalidError(f"Checkout '{checkout_id}' is '{effective_status}', not active.")
    return checkout


def _ensure_policy_eligible(db: Session, checkout: Checkout) -> None:
    """Re-derive, from scratch, that this checkout is currently permitted to
    be paid. Reuses the M4 policy/authorization records rather than
    re-implementing their rules — this never decides policy itself, it only
    reads what `app.commerce.policy.service` already decided."""
    decision = policy_repository.get_decision_by_checkout(db, checkout.id)
    if decision is None:
        raise PolicyDecisionNotFoundError(
            f"Checkout '{checkout.id}' has not been evaluated against policy yet."
        )

    if decision.decision == DECISION_DENY:
        raise PolicyDeniedError(
            f"Checkout '{checkout.id}' was denied by policy; it cannot be paid."
        )

    if decision.decision == DECISION_REQUIRE_AUTHORIZATION:
        authorization = policy_repository.get_authorization_by_checkout(db, checkout.id)
        if authorization is None:
            raise AuthorizationRequiredError(
                f"Checkout '{checkout.id}' requires authorization before it can be paid."
            )
        if (
            authorization.amount_minor_units != checkout.total_minor_units
            or authorization.currency != checkout.currency
        ):
            raise AuthorizationInvalidError(
                f"Checkout '{checkout.id}''s authorization no longer matches its current "
                "amount/currency."
            )
    elif decision.decision != DECISION_ALLOW:
        raise CheckoutInvalidError(f"Checkout '{checkout.id}' has an unrecognized policy decision.")


def initiate_payment(db: Session, *, checkout_id: uuid.UUID, provider: PaymentProvider) -> Payment:
    checkout = _load_payable_checkout(db, checkout_id)
    _ensure_policy_eligible(db, checkout)

    existing = payment_repository.get_payment_by_checkout(db, checkout_id)
    if existing is not None:
        # Belt-and-suspenders: `_load_payable_checkout` above already raises
        # `CheckoutAlreadyPaidError` once a checkout is completed, so this
        # can't currently be reached with a successful payment — kept
        # explicit anyway, the same reasoning ADR 0006 applies to
        # `authorize_checkout`'s own double-check.
        if existing.status == STATUS_SUCCESS:
            raise CheckoutAlreadyPaidError(f"Checkout '{checkout_id}' has already been paid.")
        if existing.status == STATUS_CREATED:
            # Idempotent: an order already exists for this attempt. Never
            # ask the provider to create a second one for it.
            return existing

    try:
        order = provider.create_order(
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
            receipt=str(checkout.id),
        )
    except ProviderTimeoutError as exc:
        raise CommercePaymentProviderTimeoutError(str(exc)) from exc
    except ProviderError as exc:
        raise CommercePaymentProviderError(str(exc)) from exc

    if existing is not None:
        # Retrying after a previous failed attempt: reuse the durable row so
        # a checkout can never end up with two live `Payment` records.
        existing.provider_order_id = order.provider_order_id
        existing.provider_payment_id = None
        existing.amount_minor_units = checkout.total_minor_units
        existing.currency = checkout.currency
        existing.status = STATUS_CREATED
        existing.failure_code = None
        existing.failure_message = None
        payment = existing
    else:
        payment = Payment(
            checkout_id=checkout.id,
            provider=PROVIDER_NAME,
            provider_order_id=order.provider_order_id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
            status=STATUS_CREATED,
            idempotency_key=str(checkout.id),
        )
        db.add(payment)

    db.flush()
    db.refresh(payment)
    return payment


def get_payment(db: Session, checkout_id: uuid.UUID) -> Payment:
    payment = payment_repository.get_payment_by_checkout(db, checkout_id)
    if payment is None:
        raise PaymentNotFoundError(f"No payment has been initiated for checkout '{checkout_id}'.")
    return payment


def confirm_payment(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    provider_order_id: str,
    provider_payment_id: str,
    signature: str,
    provider: PaymentProvider,
) -> Payment:
    payment = payment_repository.get_payment_by_checkout(db, checkout_id)
    if payment is None:
        raise PaymentNotFoundError(f"No payment has been initiated for checkout '{checkout_id}'.")

    if payment.status == STATUS_SUCCESS:
        # Idempotent re-confirmation: safe no-op, never re-verifies or
        # re-completes a checkout that's already done.
        if payment.provider_payment_id != provider_payment_id:
            raise InvalidPaymentStateError(
                f"Payment for checkout '{checkout_id}' already succeeded with a different "
                "provider payment id."
            )
        return payment

    if payment.status != STATUS_CREATED:
        raise InvalidPaymentStateError(
            f"Payment for checkout '{checkout_id}' is '{payment.status}'; initiate a new "
            "payment before confirming."
        )

    # The order id the client claims must match what *we* created and
    # persisted — never trust a client-supplied order id as authoritative.
    if provider_order_id != payment.provider_order_id:
        raise InvalidPaymentStateError(
            f"Payment for checkout '{checkout_id}' does not match the order being confirmed."
        )

    # Re-verify eligibility against *live* state before completing anything —
    # closes the window between initiation and confirmation, the same
    # principle `authorize_checkout` applies between evaluation and approval.
    try:
        checkout = _load_payable_checkout(db, checkout_id)
        _ensure_policy_eligible(db, checkout)
    except CommerceError as exc:
        payment.status = STATUS_FAILED
        payment.failure_code = exc.code
        payment.failure_message = exc.message
        db.flush()
        raise

    valid = provider.verify_payment(
        provider_order_id=payment.provider_order_id,
        provider_payment_id=provider_payment_id,
        signature=signature,
    )
    if not valid:
        error = InvalidPaymentSignatureError(
            f"Signature verification failed for checkout '{checkout_id}'; payment rejected."
        )
        payment.status = STATUS_FAILED
        payment.failure_code = error.code
        payment.failure_message = error.message
        db.flush()
        raise error

    payment.provider_payment_id = provider_payment_id
    payment.status = STATUS_SUCCESS
    checkout.status = "completed"
    db.flush()
    db.refresh(payment)
    return payment
