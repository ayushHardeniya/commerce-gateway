import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    AuthorizationInvalidError,
    AuthorizationRequiredError,
    CheckoutAlreadyPaidError,
    CheckoutExpiredError,
    CheckoutInvalidError,
    CheckoutNotFoundError,
    InvalidPaymentSignatureError,
    InvalidPaymentStateError,
    PaymentNotFoundError,
    PaymentProviderError,
    PaymentProviderTimeoutError,
    PolicyDecisionNotFoundError,
    PolicyDeniedError,
)
from app.commerce.payment import service as payment_service
from app.commerce.policy import service as policy_service
from tests.commerce.payment.conftest import FakePaymentProvider

CHECKOUT_TOTAL = 2000

# --- initiate_payment: eligibility ---


def test_initiate_payment_missing_checkout_raises(
    db_session: Session, fake_provider: FakePaymentProvider
) -> None:
    with pytest.raises(CheckoutNotFoundError):
        payment_service.initiate_payment(
            db_session, checkout_id=uuid.uuid4(), provider=fake_provider
        )


def test_initiate_payment_not_evaluated_raises(
    db_session: Session, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    with pytest.raises(PolicyDecisionNotFoundError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )
    assert fake_provider.created_orders == []


def test_initiate_payment_denied_checkout_rejected(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    # A currency-mismatched policy denies an otherwise-active checkout —
    # the one way to get `decision == deny` without the checkout itself
    # being expired/cancelled (see `app.commerce.policy.service._decide`).
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="EUR"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    with pytest.raises(PolicyDeniedError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )
    # Denied checkout: Razorpay must never be called at all.
    assert fake_provider.created_orders == []


def test_initiate_payment_cancelled_checkout_rejected(
    db_session: Session, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    checkout.status = "cancelled"
    db_session.flush()

    with pytest.raises(CheckoutInvalidError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )
    assert fake_provider.created_orders == []


def test_initiate_payment_missing_authorization_rejected(
    db_session: Session, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.evaluate_checkout(db_session, checkout.id)  # default policy -> require_auth

    with pytest.raises(AuthorizationRequiredError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )
    assert fake_provider.created_orders == []


def test_initiate_payment_expired_checkout_rejected(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    checkout.created_at = datetime.now(UTC) - timedelta(hours=1)
    checkout.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    with pytest.raises(CheckoutExpiredError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )
    assert fake_provider.created_orders == []


def test_initiate_payment_completed_checkout_rejected(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    checkout.status = "completed"
    db_session.flush()

    with pytest.raises(CheckoutAlreadyPaidError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )
    assert fake_provider.created_orders == []


# --- initiate_payment: happy paths ---


def test_initiate_payment_allow_checkout_succeeds(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    payment = payment_service.initiate_payment(
        db_session, checkout_id=checkout.id, provider=fake_provider
    )

    assert payment.checkout_id == checkout.id
    assert payment.status == payment_service.STATUS_CREATED
    assert payment.amount_minor_units == CHECKOUT_TOTAL
    assert payment.currency == checkout.currency
    assert len(fake_provider.created_orders) == 1


def test_initiate_payment_authorized_checkout_succeeds(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    policy_service.authorize_checkout(
        db_session,
        checkout_id=checkout.id,
        amount_minor_units=checkout.total_minor_units,
        currency=checkout.currency,
    )

    payment = payment_service.initiate_payment(
        db_session, checkout_id=checkout.id, provider=fake_provider
    )

    assert payment.status == payment_service.STATUS_CREATED


def test_initiate_payment_authorization_amount_drifted_rejected(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    policy_service.authorize_checkout(
        db_session,
        checkout_id=checkout.id,
        amount_minor_units=checkout.total_minor_units,
        currency=checkout.currency,
    )
    checkout.total_minor_units += 500
    db_session.flush()

    with pytest.raises(AuthorizationInvalidError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )


# --- initiate_payment: caller cannot override amount/currency ---


def test_initiate_payment_amount_always_from_checkout(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    """`initiate_payment` has no amount/currency parameter at all — this
    pins that the persisted payment (and the order sent to the provider)
    always reflects the checkout's own authoritative total."""
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    payment = payment_service.initiate_payment(
        db_session, checkout_id=checkout.id, provider=fake_provider
    )

    assert payment.amount_minor_units == checkout.total_minor_units
    assert payment.currency == checkout.currency
    assert fake_provider.created_orders[0].amount_minor_units == checkout.total_minor_units
    assert fake_provider.created_orders[0].currency == checkout.currency


# --- initiate_payment: duplicate protection / provider outcomes ---


def test_initiate_payment_twice_while_created_is_idempotent(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    first = payment_service.initiate_payment(
        db_session, checkout_id=checkout.id, provider=fake_provider
    )
    second = payment_service.initiate_payment(
        db_session, checkout_id=checkout.id, provider=fake_provider
    )

    assert first.id == second.id
    assert first.provider_order_id == second.provider_order_id
    # Never asked the provider to create a second order for the same attempt.
    assert len(fake_provider.created_orders) == 1


def test_initiate_payment_provider_failure_raises_provider_error(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    fake_provider.queue_create_order_failure()

    with pytest.raises(PaymentProviderError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )


def test_initiate_payment_provider_timeout_raises_provider_timeout_error(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    fake_provider.queue_create_order_timeout()

    with pytest.raises(PaymentProviderTimeoutError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )


def test_initiate_payment_retries_after_provider_failure(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    fake_provider.queue_create_order_failure()

    with pytest.raises(PaymentProviderError):
        payment_service.initiate_payment(
            db_session, checkout_id=checkout.id, provider=fake_provider
        )

    payment = payment_service.initiate_payment(
        db_session, checkout_id=checkout.id, provider=fake_provider
    )
    assert payment.status == payment_service.STATUS_CREATED
    assert len(fake_provider.created_orders) == 1


# --- confirm_payment ---


def _initiated_payment(db_session: Session, merchant: Merchant, checkout: Checkout, provider):
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    return payment_service.initiate_payment(db_session, checkout_id=checkout.id, provider=provider)


def test_confirm_payment_missing_payment_raises(
    db_session: Session, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    with pytest.raises(PaymentNotFoundError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id="order_fake_1",
            provider_payment_id="pay_fake_1",
            signature="sig",
            provider=fake_provider,
        )


def test_confirm_payment_valid_signature_succeeds_and_completes_checkout(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    payment = _initiated_payment(db_session, merchant, checkout, fake_provider)
    fake_provider.next_signature_valid = True

    confirmed = payment_service.confirm_payment(
        db_session,
        checkout_id=checkout.id,
        provider_order_id=payment.provider_order_id,
        provider_payment_id="pay_fake_1",
        signature="valid-sig",
        provider=fake_provider,
    )

    assert confirmed.status == payment_service.STATUS_SUCCESS
    assert confirmed.provider_payment_id == "pay_fake_1"
    assert checkout.status == "completed"


def test_confirm_payment_invalid_signature_rejected_and_checkout_not_completed(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    payment = _initiated_payment(db_session, merchant, checkout, fake_provider)
    fake_provider.next_signature_valid = False

    with pytest.raises(InvalidPaymentSignatureError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id="pay_fake_1",
            signature="bad-sig",
            provider=fake_provider,
        )

    assert payment.status == payment_service.STATUS_FAILED
    assert checkout.status == "active"


def test_confirm_payment_order_id_mismatch_rejected(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    _initiated_payment(db_session, merchant, checkout, fake_provider)

    with pytest.raises(InvalidPaymentStateError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id="order_not_ours",
            provider_payment_id="pay_fake_1",
            signature="sig",
            provider=fake_provider,
        )
    assert checkout.status == "active"


def test_confirm_payment_expired_checkout_rejected_before_verification(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    payment = _initiated_payment(db_session, merchant, checkout, fake_provider)
    checkout.created_at = datetime.now(UTC) - timedelta(hours=1)
    checkout.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    with pytest.raises(CheckoutExpiredError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id="pay_fake_1",
            signature="valid-sig",
            provider=fake_provider,
        )

    assert payment.status == payment_service.STATUS_FAILED
    # A checkout that's no longer eligible is rejected before we even ask
    # the provider whether the signature is valid.
    assert fake_provider.verify_calls == []


def test_confirm_payment_success_is_idempotent(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    payment = _initiated_payment(db_session, merchant, checkout, fake_provider)
    fake_provider.next_signature_valid = True
    payment_service.confirm_payment(
        db_session,
        checkout_id=checkout.id,
        provider_order_id=payment.provider_order_id,
        provider_payment_id="pay_fake_1",
        signature="valid-sig",
        provider=fake_provider,
    )
    calls_after_first = len(fake_provider.verify_calls)

    again = payment_service.confirm_payment(
        db_session,
        checkout_id=checkout.id,
        provider_order_id=payment.provider_order_id,
        provider_payment_id="pay_fake_1",
        signature="valid-sig",
        provider=fake_provider,
    )

    assert again.status == payment_service.STATUS_SUCCESS
    assert checkout.status == "completed"
    # Never re-verifies (and never re-completes) an already-successful payment.
    assert len(fake_provider.verify_calls) == calls_after_first


def test_confirm_payment_success_replayed_with_different_payment_id_rejected(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    payment = _initiated_payment(db_session, merchant, checkout, fake_provider)
    fake_provider.next_signature_valid = True
    payment_service.confirm_payment(
        db_session,
        checkout_id=checkout.id,
        provider_order_id=payment.provider_order_id,
        provider_payment_id="pay_fake_1",
        signature="valid-sig",
        provider=fake_provider,
    )

    with pytest.raises(InvalidPaymentStateError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id="pay_fake_DIFFERENT",
            signature="valid-sig",
            provider=fake_provider,
        )


def test_confirm_payment_after_failure_requires_new_initiation(
    db_session: Session, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    payment = _initiated_payment(db_session, merchant, checkout, fake_provider)
    fake_provider.next_signature_valid = False
    with pytest.raises(InvalidPaymentSignatureError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id="pay_fake_1",
            signature="bad-sig",
            provider=fake_provider,
        )

    with pytest.raises(InvalidPaymentStateError):
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id="pay_fake_1",
            signature="another-sig",
            provider=fake_provider,
        )


def test_get_payment_missing_raises(db_session: Session, checkout: Checkout) -> None:
    with pytest.raises(PaymentNotFoundError):
        payment_service.get_payment(db_session, checkout.id)
