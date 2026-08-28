import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commerce.checkout.models import Checkout
from app.commerce.transaction.models import Transaction


def test_transaction_state_must_be_a_known_value(db_session: Session) -> None:
    db_session.add(Transaction(state="bogus"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_transaction_defaults_to_discovered(db_session: Session) -> None:
    transaction = Transaction()
    db_session.add(transaction)
    db_session.flush()
    db_session.refresh(transaction)

    assert transaction.state == "discovered"
    assert transaction.cart_id is None
    assert transaction.checkout_id is None


def test_two_transactions_can_share_no_checkout(db_session: Session) -> None:
    """`checkout_id` is nullable and unique-when-set: multiple transactions
    with no checkout yet must not collide against each other."""
    first = Transaction()
    second = Transaction()
    db_session.add_all([first, second])
    db_session.flush()

    assert first.checkout_id is None
    assert second.checkout_id is None


def test_checkout_id_must_be_unique_once_set(db_session: Session, checkout: Checkout) -> None:
    db_session.add(Transaction(checkout_id=checkout.id, state="checkout_created"))
    db_session.flush()

    db_session.add(Transaction(checkout_id=checkout.id, state="checkout_created"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_checkout_with_transaction_is_restricted(
    db_session: Session, checkout: Checkout
) -> None:
    db_session.add(Transaction(checkout_id=checkout.id, state="checkout_created"))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Checkout).where(Checkout.id == checkout.id))
        db_session.flush()
