import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.commerce.cart.models import Cart
from app.commerce.checkout import service
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    CheckoutNotFoundError,
    EmptyCartError,
    InvalidCartStateError,
    PriceChangedError,
    ProductUnavailableError,
)

# --- valid creation ---


def test_create_checkout(db_session: Session, cart_with_item: Cart) -> None:
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)

    assert checkout.cart_id == cart_with_item.id
    assert checkout.status == "active"
    assert checkout.effective_status == "active"
    assert checkout.currency == cart_with_item.currency
    assert len(checkout.items) == 1


def test_create_checkout_total_is_deterministic_sum(
    db_session: Session, cart_with_item: Cart
) -> None:
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)

    assert checkout.total_minor_units == cart_with_item.subtotal_minor_units


def test_create_checkout_snapshots_line_items(
    db_session: Session, cart_with_item: Cart, product: Product
) -> None:
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)

    item = checkout.items[0]
    assert item.product_id == product.id
    assert item.product_name == product.name
    assert item.product_sku == product.sku
    assert item.quantity == 2
    assert item.unit_price_minor_units == product.price_minor_units


def test_create_checkout_sets_expiry_in_the_future(
    db_session: Session, cart_with_item: Cart
) -> None:
    before = datetime.now(UTC)
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)

    assert checkout.expires_at > before


# --- empty cart ---


def test_create_checkout_for_empty_cart_raises(db_session: Session, cart: Cart) -> None:
    with pytest.raises(EmptyCartError):
        service.create_checkout(db_session, cart_id=cart.id)


# --- unavailable product ---


def test_create_checkout_rejects_unavailable_product(
    db_session: Session, cart_with_item: Cart, product: Product
) -> None:
    product.stock_quantity = 0
    db_session.flush()

    with pytest.raises(ProductUnavailableError):
        service.create_checkout(db_session, cart_id=cart_with_item.id)


# --- price changed ---


def test_create_checkout_detects_price_change(
    db_session: Session, cart_with_item: Cart, product: Product
) -> None:
    original_price = product.price_minor_units
    product.price_minor_units = original_price + 500
    db_session.flush()

    with pytest.raises(PriceChangedError) as exc_info:
        service.create_checkout(db_session, cart_id=cart_with_item.id)

    change = exc_info.value.changes[0]
    assert change.product_id == product.id
    assert change.previous_unit_price_minor_units == original_price
    assert change.current_unit_price_minor_units == original_price + 500


def test_create_checkout_does_not_silently_use_new_price(
    db_session: Session, cart_with_item: Cart, product: Product
) -> None:
    original_snapshot_price = cart_with_item.items[0].unit_price_minor_units
    product.price_minor_units = product.price_minor_units + 1
    db_session.flush()

    with pytest.raises(PriceChangedError):
        service.create_checkout(db_session, cart_id=cart_with_item.id)

    # The failed attempt must not have created a checkout, nor silently
    # rewritten the cart item's price snapshot to the new price.
    assert db_session.scalars(select(Checkout)).first() is None
    assert cart_with_item.items[0].unit_price_minor_units == original_snapshot_price


# --- invalid cart state ---


def test_create_second_active_checkout_for_same_cart_raises(
    db_session: Session, cart_with_item: Cart
) -> None:
    service.create_checkout(db_session, cart_id=cart_with_item.id)

    with pytest.raises(InvalidCartStateError):
        service.create_checkout(db_session, cart_id=cart_with_item.id)


def _expire(db_session: Session, checkout: Checkout) -> None:
    """Back-date a checkout so it reads as expired "now" — `expires_at` must
    stay after `created_at` (ck_checkouts_expires_after_created), so both
    move into the past together rather than just `expires_at` alone."""
    now = datetime.now(UTC)
    checkout.created_at = now - timedelta(hours=1)
    checkout.expires_at = now - timedelta(minutes=1)
    db_session.flush()


def test_create_checkout_allowed_again_after_previous_one_expired(
    db_session: Session, cart_with_item: Cart
) -> None:
    first = service.create_checkout(db_session, cart_id=cart_with_item.id)
    _expire(db_session, first)

    second = service.create_checkout(db_session, cart_id=cart_with_item.id)

    assert second.id != first.id


# --- retrieval ---


def test_get_checkout(db_session: Session, cart_with_item: Cart) -> None:
    created = service.create_checkout(db_session, cart_id=cart_with_item.id)

    fetched = service.get_checkout(db_session, created.id)

    assert fetched.id == created.id


def test_get_missing_checkout_raises(db_session: Session) -> None:
    with pytest.raises(CheckoutNotFoundError):
        service.get_checkout(db_session, uuid.uuid4())


# --- expiry (status model) ---


def test_checkout_effective_status_becomes_expired_after_expiry(
    db_session: Session, cart_with_item: Cart
) -> None:
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)

    _expire(db_session, checkout)

    assert checkout.status == "active"
    assert checkout.effective_status == "expired"


def test_checkout_expiry_is_never_persisted_to_the_status_column(
    db_session: Session, cart_with_item: Cart
) -> None:
    """ "expired" is a derived read, never a stored value — mirrors
    Product.is_available. Re-fetching the row must not have silently
    written "expired" into the status column."""
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)
    _expire(db_session, checkout)

    _ = checkout.effective_status  # trigger the read

    refetched = db_session.get(Checkout, checkout.id)
    assert refetched is not None
    assert refetched.status == "active"
