import uuid

import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product
from app.commerce.cart import service as cart_service
from app.commerce.cart.models import Cart
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    CartNotFoundError,
    CheckoutAlreadyHasTransactionError,
    CheckoutNotFoundError,
    InvalidTransactionTransitionError,
    TransactionInputMismatchError,
    TransactionNotFoundError,
)
from app.commerce.payment import service as payment_service
from app.commerce.policy import service as policy_service
from app.commerce.transaction import repository as transaction_repository
from app.commerce.transaction import service as transaction_service
from tests.commerce.payment.conftest import FakePaymentProvider

# --- create_transaction ---


def test_create_transaction_with_no_references_starts_discovered(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)

    assert transaction.state == transaction_service.STATE_DISCOVERED
    assert transaction.cart_id is None
    assert transaction.checkout_id is None


def test_create_transaction_with_cart_starts_cart_created(db_session: Session, cart: Cart) -> None:
    transaction = transaction_service.create_transaction(db_session, cart_id=cart.id)

    assert transaction.state == transaction_service.STATE_CART_CREATED
    assert transaction.cart_id == cart.id
    assert transaction.checkout_id is None


def test_create_transaction_missing_cart_raises(db_session: Session) -> None:
    with pytest.raises(CartNotFoundError):
        transaction_service.create_transaction(db_session, cart_id=uuid.uuid4())


def test_create_transaction_with_checkout_starts_checkout_created_and_derives_cart(
    db_session: Session, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    assert transaction.state == transaction_service.STATE_CHECKOUT_CREATED
    assert transaction.checkout_id == checkout.id
    assert transaction.cart_id == checkout.cart_id


def test_create_transaction_missing_checkout_raises(db_session: Session) -> None:
    with pytest.raises(CheckoutNotFoundError):
        transaction_service.create_transaction(db_session, checkout_id=uuid.uuid4())


def test_create_transaction_mismatched_cart_and_checkout_raises(
    db_session: Session, checkout: Checkout
) -> None:
    with pytest.raises(TransactionInputMismatchError):
        transaction_service.create_transaction(
            db_session, cart_id=uuid.uuid4(), checkout_id=checkout.id
        )


def test_create_transaction_checkout_already_linked_raises(
    db_session: Session, checkout: Checkout
) -> None:
    first = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    with pytest.raises(CheckoutAlreadyHasTransactionError) as exc_info:
        transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    assert exc_info.value.transaction_id == first.id
    assert exc_info.value.code == "transaction_already_exists"


# --- get_transaction_by_checkout ---


def test_get_transaction_by_checkout(db_session: Session, checkout: Checkout) -> None:
    created = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    found = transaction_service.get_transaction_by_checkout(db_session, checkout.id)

    assert found.id == created.id


def test_get_transaction_by_checkout_missing_raises(
    db_session: Session, checkout: Checkout
) -> None:
    with pytest.raises(TransactionNotFoundError):
        transaction_service.get_transaction_by_checkout(db_session, checkout.id)


# --- list_transactions ---


def test_list_transactions_empty(db_session: Session) -> None:
    items, total = transaction_service.list_transactions(db_session)
    assert items == []
    assert total == 0


def test_list_transactions_orders_newest_first(db_session: Session, checkout: Checkout) -> None:
    first = transaction_service.create_transaction(db_session)
    second = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    items, total = transaction_service.list_transactions(db_session)

    assert total == 2
    assert [item.id for item in items] == [second.id, first.id]


def test_list_transactions_respects_limit_and_offset(db_session: Session) -> None:
    created = [transaction_service.create_transaction(db_session) for _ in range(3)]

    items, total = transaction_service.list_transactions(db_session, limit=2, offset=1)

    assert total == 3
    assert len(items) == 2
    assert [item.id for item in items] == [created[1].id, created[0].id]


# --- get_transaction ---


def test_get_transaction_missing_raises(db_session: Session) -> None:
    with pytest.raises(TransactionNotFoundError):
        transaction_service.get_transaction(db_session, uuid.uuid4())


# --- transition_transaction: FSM shape ---


def test_transition_missing_transaction_raises(db_session: Session) -> None:
    with pytest.raises(TransactionNotFoundError):
        transaction_service.transition_transaction(
            db_session, transaction_id=uuid.uuid4(), to_state=transaction_service.STATE_CANCELLED
        )


def test_transition_skipping_a_state_is_rejected(db_session: Session) -> None:
    """discovered -> checkout_created is not an edge; cart_created must be
    passed through first, even though the caller could in principle supply
    every field a later state would need."""
    transaction = transaction_service.create_transaction(db_session)

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CHECKOUT_CREATED,
        )


def test_transition_discovered_to_cart_created_requires_cart_id(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)

    with pytest.raises(TransactionInputMismatchError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CART_CREATED,
        )


def test_transition_discovered_to_cart_created_succeeds(db_session: Session, cart: Cart) -> None:
    transaction = transaction_service.create_transaction(db_session)

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CART_CREATED,
        cart_id=cart.id,
    )

    assert updated.state == transaction_service.STATE_CART_CREATED
    assert updated.cart_id == cart.id


def test_transition_cart_created_to_checkout_created_requires_checkout_id(
    db_session: Session, cart: Cart
) -> None:
    transaction = transaction_service.create_transaction(db_session, cart_id=cart.id)

    with pytest.raises(TransactionInputMismatchError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CHECKOUT_CREATED,
        )


def test_transition_cart_created_to_checkout_created_wrong_cart_rejected(
    db_session: Session, merchant: Merchant, product: Product, checkout: Checkout
) -> None:
    """A second, unrelated cart/checkout pair — the transaction anchored on
    the *other* cart must not be allowed to attach this checkout to itself."""
    other_cart = cart_service.create_cart(db_session, merchant_id=merchant.id)
    cart_service.add_item(db_session, cart_id=other_cart.id, product_id=product.id, quantity=1)

    transaction = transaction_service.create_transaction(db_session, cart_id=other_cart.id)

    with pytest.raises(TransactionInputMismatchError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CHECKOUT_CREATED,
            checkout_id=checkout.id,
        )


def test_transition_cart_created_to_checkout_created_already_linked_rejected(
    db_session: Session, checkout: Checkout
) -> None:
    other = transaction_service.create_transaction(db_session, cart_id=checkout.cart_id)
    existing = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    with pytest.raises(CheckoutAlreadyHasTransactionError) as exc_info:
        transaction_service.transition_transaction(
            db_session,
            transaction_id=other.id,
            to_state=transaction_service.STATE_CHECKOUT_CREATED,
            checkout_id=checkout.id,
        )
    assert exc_info.value.transaction_id == existing.id


def test_transition_cart_created_to_checkout_created_succeeds(
    db_session: Session, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, cart_id=checkout.cart_id)

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CHECKOUT_CREATED,
        checkout_id=checkout.id,
    )

    assert updated.state == transaction_service.STATE_CHECKOUT_CREATED
    assert updated.checkout_id == checkout.id


# --- transition_transaction: policy-guarded edges ---


def test_transition_checkout_created_to_policy_pending_succeeds(
    db_session: Session, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )

    assert updated.state == transaction_service.STATE_POLICY_PENDING


def test_transition_policy_pending_to_authorized_without_decision_rejected(
    db_session: Session, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_AUTHORIZED,
        )


def test_transition_policy_pending_to_authorized_via_allow(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_AUTHORIZED,
    )

    assert updated.state == transaction_service.STATE_AUTHORIZED


def test_transition_policy_pending_to_authorized_requires_human_authorization(
    db_session: Session, checkout: Checkout
) -> None:
    # Default policy (no explicit MerchantPolicy) -> require_authorization.
    policy_service.evaluate_checkout(db_session, checkout.id)

    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_AUTHORIZED,
        )

    policy_service.authorize_checkout(
        db_session,
        checkout_id=checkout.id,
        amount_minor_units=checkout.total_minor_units,
        currency=checkout.currency,
    )

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_AUTHORIZED,
    )
    assert updated.state == transaction_service.STATE_AUTHORIZED


def test_transition_policy_pending_to_policy_denied_requires_real_denial(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )

    # No PolicyDecision recorded yet at all.
    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_POLICY_DENIED,
        )

    # A currency-mismatched policy is the one way to get `deny` on an
    # otherwise-active checkout (mirrors `test_service.py` in payment).
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="EUR"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_DENIED,
    )
    assert updated.state == transaction_service.STATE_POLICY_DENIED
    assert updated.failure_reason == "currency_mismatch"


# --- transition_transaction: payment-guarded edges ---


def _to_authorized(db_session: Session, merchant: Merchant, checkout: Checkout):
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )
    return transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_AUTHORIZED,
    )


def test_transition_authorized_to_payment_pending_requires_live_payment(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    transaction = _to_authorized(db_session, merchant, checkout)

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_PAYMENT_PENDING,
        )


def test_full_lifecycle_allow_to_order_confirmed(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    provider = FakePaymentProvider()
    transaction = _to_authorized(db_session, merchant, checkout)

    payment_service.initiate_payment(db_session, checkout_id=checkout.id, provider=provider)
    pending = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_PAYMENT_PENDING,
    )
    assert pending.state == transaction_service.STATE_PAYMENT_PENDING

    payment = payment_service.get_payment(db_session, checkout.id)
    payment_service.confirm_payment(
        db_session,
        checkout_id=checkout.id,
        provider_order_id=payment.provider_order_id,
        provider_payment_id="pay_fake_1",
        signature="valid-sig",
        provider=provider,
    )

    success = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_PAYMENT_SUCCESS,
    )
    assert success.state == transaction_service.STATE_PAYMENT_SUCCESS

    confirmed = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_ORDER_CONFIRMED,
    )
    assert confirmed.state == transaction_service.STATE_ORDER_CONFIRMED


def test_payment_success_cannot_be_asserted_without_a_real_payment(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    """Pins the determinism rule: nothing but a real `Payment.status ==
    'success'` row can move a transaction into `payment_success` — an
    unverified claim (e.g. from an LLM) is rejected the same as any other
    invalid transition."""
    provider = FakePaymentProvider()
    transaction = _to_authorized(db_session, merchant, checkout)
    payment_service.initiate_payment(db_session, checkout_id=checkout.id, provider=provider)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_PAYMENT_PENDING,
    )

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_PAYMENT_SUCCESS,
        )


def test_payment_failure_and_retry(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    provider = FakePaymentProvider()
    provider.next_signature_valid = False
    transaction = _to_authorized(db_session, merchant, checkout)
    payment_service.initiate_payment(db_session, checkout_id=checkout.id, provider=provider)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_PAYMENT_PENDING,
    )
    payment = payment_service.get_payment(db_session, checkout.id)
    with pytest.raises(Exception):  # noqa: B017 - InvalidPaymentSignatureError, see payment.errors
        payment_service.confirm_payment(
            db_session,
            checkout_id=checkout.id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id="pay_fake_1",
            signature="bad-sig",
            provider=provider,
        )

    failed = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_PAYMENT_FAILED,
    )
    assert failed.state == transaction_service.STATE_PAYMENT_FAILED
    assert failed.failure_reason == "invalid_payment_signature"

    # Retry: re-initiate payment, then the transaction can move back to
    # payment_pending, with its failure_reason cleared.
    provider.next_signature_valid = True
    payment_service.initiate_payment(db_session, checkout_id=checkout.id, provider=provider)
    retried = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_PAYMENT_PENDING,
    )
    assert retried.state == transaction_service.STATE_PAYMENT_PENDING
    assert retried.failure_reason is None


# --- checkout expiry ---


def test_transition_to_checkout_expired_requires_actually_expired_checkout(
    db_session: Session, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CHECKOUT_EXPIRED,
        )

    from datetime import UTC, datetime, timedelta

    checkout.created_at = datetime.now(UTC) - timedelta(hours=1)
    checkout.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CHECKOUT_EXPIRED,
    )
    assert updated.state == transaction_service.STATE_CHECKOUT_EXPIRED


# --- terminal-state protection ---


@pytest.mark.parametrize(
    "terminal_state",
    [
        transaction_service.STATE_ORDER_CONFIRMED,
        transaction_service.STATE_POLICY_DENIED,
        transaction_service.STATE_CHECKOUT_EXPIRED,
        transaction_service.STATE_CANCELLED,
        transaction_service.STATE_FAILED,
    ],
)
def test_terminal_states_have_no_outgoing_transitions(
    db_session: Session, terminal_state: str
) -> None:
    assert all(
        from_state != terminal_state for (from_state, _to) in transaction_service._TRANSITIONS
    )


def test_cancelled_transaction_cannot_transition_further(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)
    cancelled = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CANCELLED,
        failure_reason="buyer changed their mind",
    )
    assert cancelled.state == transaction_service.STATE_CANCELLED
    assert cancelled.failure_reason == "buyer changed their mind"

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_DISCOVERED,
        )
    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_FAILED,
        )


def test_failed_transaction_cannot_transition_further(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)
    failed = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_FAILED,
        failure_reason="unexpected error",
    )
    assert failed.state == transaction_service.STATE_FAILED

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CANCELLED,
        )


# --- persistence / reload ---


def test_transaction_state_persists_and_reloads_from_the_database(
    db_session: Session, cart: Cart
) -> None:
    transaction = transaction_service.create_transaction(db_session, cart_id=cart.id)
    transaction_id = transaction.id

    db_session.expire_all()  # drop the ORM identity map's cached attributes

    reloaded = transaction_repository.get_transaction_by_id(db_session, transaction_id)
    assert reloaded is not None
    assert reloaded.state == transaction_service.STATE_CART_CREATED
    assert reloaded.cart_id == cart.id
