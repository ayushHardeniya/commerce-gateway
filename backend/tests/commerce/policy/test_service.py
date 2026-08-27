import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    AlreadyAuthorizedError,
    AuthorizationDeniedError,
    AuthorizationInvalidError,
    AuthorizationNotRequiredError,
    CheckoutExpiredError,
    CheckoutInvalidError,
    CheckoutNotFoundError,
    MerchantNotFoundError,
    PolicyDecisionNotFoundError,
)
from app.commerce.policy import repository as policy_repository
from app.commerce.policy import service as policy_service

# `cart_with_item` (2 units @ 1000 minor units = 2000 total, USD) yields this
# checkout total for every test in this module.
CHECKOUT_TOTAL = 2000

# --- merchant policy: get / upsert ---


def test_get_policy_missing_merchant_raises(db_session: Session) -> None:
    with pytest.raises(MerchantNotFoundError):
        policy_service.get_policy(db_session, uuid.uuid4())


def test_get_policy_returns_none_when_unconfigured(db_session: Session, merchant: Merchant) -> None:
    assert policy_service.get_policy(db_session, merchant.id) is None


def test_upsert_policy_creates_version_one(db_session: Session, merchant: Merchant) -> None:
    policy = policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="usd"
    )

    assert policy.version == 1
    assert policy.autonomous_limit_minor_units == 5000
    assert policy.currency == "USD"


def test_upsert_policy_again_increments_version_in_place(
    db_session: Session, merchant: Merchant
) -> None:
    first = policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    second = policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )

    assert first.id == second.id
    assert second.version == 2
    assert second.autonomous_limit_minor_units == 1000
    assert policy_repository.get_policy_by_merchant(db_session, merchant.id).version == 2


# --- evaluate_checkout: decision rules ---


def test_evaluate_checkout_missing_raises(db_session: Session) -> None:
    with pytest.raises(CheckoutNotFoundError):
        policy_service.evaluate_checkout(db_session, uuid.uuid4())


def test_evaluate_checkout_default_policy_requires_authorization(
    db_session: Session, checkout: Checkout
) -> None:
    """No explicit MerchantPolicy configured: the safe default (limit 0)
    means any positive checkout total requires authorization."""
    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_REQUIRE_AUTHORIZATION
    assert decision.reason == policy_service.REASON_LIMIT_EXCEEDED
    assert decision.policy_version == policy_service.DEFAULT_POLICY_VERSION
    assert decision.autonomous_limit_minor_units == 0
    assert decision.policy_id is None


def test_evaluate_checkout_below_limit_allows(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )

    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_ALLOW
    assert decision.reason == policy_service.REASON_WITHIN_LIMIT


def test_evaluate_checkout_exactly_at_limit_allows(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session,
        merchant_id=merchant.id,
        autonomous_limit_minor_units=CHECKOUT_TOTAL,
        currency="USD",
    )

    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_ALLOW
    assert decision.reason == policy_service.REASON_WITHIN_LIMIT


def test_evaluate_checkout_above_limit_requires_authorization(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )

    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_REQUIRE_AUTHORIZATION
    assert decision.reason == policy_service.REASON_LIMIT_EXCEEDED


def test_evaluate_expired_checkout_denies(db_session: Session, checkout: Checkout) -> None:
    checkout.created_at = datetime.now(UTC) - timedelta(hours=1)
    checkout.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_DENY
    assert decision.reason == policy_service.REASON_CHECKOUT_EXPIRED


def test_evaluate_cancelled_checkout_denies(db_session: Session, checkout: Checkout) -> None:
    checkout.status = "cancelled"
    db_session.flush()

    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_DENY
    assert decision.reason == policy_service.REASON_CHECKOUT_INVALID


def test_evaluate_checkout_currency_mismatch_denies(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="EUR"
    )

    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.decision == policy_service.DECISION_DENY
    assert decision.reason == policy_service.REASON_CURRENCY_MISMATCH


def test_evaluate_checkout_preserves_currency(db_session: Session, checkout: Checkout) -> None:
    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    assert decision.currency == checkout.currency
    assert decision.amount_minor_units == checkout.total_minor_units


def test_evaluate_checkout_is_idempotent(db_session: Session, checkout: Checkout) -> None:
    first = policy_service.evaluate_checkout(db_session, checkout.id)
    second = policy_service.evaluate_checkout(db_session, checkout.id)

    assert first.id == second.id


def test_evaluate_checkout_snapshot_survives_later_policy_change(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    """The core invariant: once a checkout has been evaluated, changing the
    merchant's policy afterward must not silently change what that decision
    meant."""
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    decision = policy_service.evaluate_checkout(db_session, checkout.id)
    assert decision.decision == policy_service.DECISION_ALLOW
    assert decision.policy_version == 1

    # Merchant tightens the limit after the decision was already made.
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=0, currency="USD"
    )

    re_fetched = policy_service.evaluate_checkout(db_session, checkout.id)
    assert re_fetched.id == decision.id
    assert re_fetched.decision == policy_service.DECISION_ALLOW
    assert re_fetched.policy_version == 1
    assert re_fetched.autonomous_limit_minor_units == 5000


def test_get_decision_missing_raises(db_session: Session, checkout: Checkout) -> None:
    with pytest.raises(PolicyDecisionNotFoundError):
        policy_service.get_decision(db_session, checkout.id)


# --- authorize_checkout ---


def test_authorize_checkout_requires_authorization(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    decision = policy_service.evaluate_checkout(db_session, checkout.id)

    authorization = policy_service.authorize_checkout(
        db_session,
        checkout_id=checkout.id,
        amount_minor_units=checkout.total_minor_units,
        currency=checkout.currency,
    )

    assert authorization.checkout_id == checkout.id
    assert authorization.policy_decision_id == decision.id
    assert authorization.amount_minor_units == checkout.total_minor_units
    assert authorization.currency == checkout.currency


def test_authorize_checkout_not_evaluated_raises(db_session: Session, checkout: Checkout) -> None:
    with pytest.raises(PolicyDecisionNotFoundError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
        )


def test_authorize_allowed_checkout_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=999_999, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    with pytest.raises(AuthorizationNotRequiredError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
        )


def test_authorize_denied_checkout_raises(db_session: Session, checkout: Checkout) -> None:
    checkout.status = "cancelled"
    db_session.flush()
    policy_service.evaluate_checkout(db_session, checkout.id)

    with pytest.raises(AuthorizationDeniedError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
        )


def test_authorize_wrong_amount_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    with pytest.raises(AuthorizationInvalidError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units + 1,
            currency=checkout.currency,
        )


def test_authorize_wrong_currency_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    with pytest.raises(AuthorizationInvalidError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency="EUR",
        )


def test_authorize_after_checkout_amount_drifted_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    decision = policy_service.evaluate_checkout(db_session, checkout.id)
    original_amount = decision.amount_minor_units

    checkout.total_minor_units += 500
    db_session.flush()

    with pytest.raises(AuthorizationInvalidError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=original_amount,
            currency=checkout.currency,
        )


def test_authorize_after_checkout_currency_drifted_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    decision = policy_service.evaluate_checkout(db_session, checkout.id)
    original_currency = decision.currency

    checkout.currency = "EUR"
    db_session.flush()

    with pytest.raises(AuthorizationInvalidError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=original_currency,
        )


def test_authorize_expired_checkout_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    checkout.created_at = datetime.now(UTC) - timedelta(hours=1)
    checkout.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    with pytest.raises(CheckoutExpiredError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
        )


def test_authorize_completed_checkout_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    checkout.status = "completed"
    db_session.flush()

    with pytest.raises(CheckoutInvalidError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
        )


def test_authorize_twice_raises(
    db_session: Session, merchant: Merchant, checkout: Checkout
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

    with pytest.raises(AlreadyAuthorizedError):
        policy_service.authorize_checkout(
            db_session,
            checkout_id=checkout.id,
            amount_minor_units=checkout.total_minor_units,
            currency=checkout.currency,
        )
