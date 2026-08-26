from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.commerce.cart.models import Cart
from app.commerce.checkout.models import Checkout, CheckoutItem


def _make_checkout(cart: Cart, **overrides) -> Checkout:
    now = datetime.now(UTC)
    defaults = dict(
        cart_id=cart.id,
        status="active",
        total_minor_units=1000,
        currency="USD",
        expires_at=now + timedelta(minutes=15),
    )
    defaults.update(overrides)
    return Checkout(**defaults)


def test_checkout_status_must_be_a_known_value(db_session: Session, cart: Cart) -> None:
    db_session.add(_make_checkout(cart, status="bogus"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_checkout_total_must_be_non_negative(db_session: Session, cart: Cart) -> None:
    db_session.add(_make_checkout(cart, total_minor_units=-1))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_checkout_currency_must_be_three_chars(db_session: Session, cart: Cart) -> None:
    db_session.add(_make_checkout(cart, currency="US"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_checkout_expires_at_must_be_after_created_at(db_session: Session, cart: Cart) -> None:
    now = datetime.now(UTC)
    db_session.add(_make_checkout(cart, created_at=now, expires_at=now - timedelta(minutes=1)))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_checkout_item_quantity_must_be_positive(db_session: Session, cart: Cart) -> None:
    checkout = _make_checkout(cart)
    db_session.add(checkout)
    db_session.flush()

    db_session.add(
        CheckoutItem(
            checkout_id=checkout.id,
            product_name="Widget",
            product_sku="SKU-1",
            quantity=0,
            unit_price_minor_units=100,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_cart_with_active_checkout_is_restricted(db_session: Session, cart: Cart) -> None:
    db_session.add(_make_checkout(cart))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Cart).where(Cart.id == cart.id))
        db_session.flush()


def test_deleting_product_sets_checkout_item_product_id_null(
    db_session: Session, cart: Cart, product: Product
) -> None:
    checkout = _make_checkout(cart)
    db_session.add(checkout)
    db_session.flush()

    item = CheckoutItem(
        checkout_id=checkout.id,
        product_id=product.id,
        product_name=product.name,
        product_sku=product.sku,
        quantity=1,
        unit_price_minor_units=product.price_minor_units,
    )
    db_session.add(item)
    db_session.flush()

    db_session.execute(delete(Product).where(Product.id == product.id))
    db_session.flush()
    db_session.expire_all()  # the raw DELETE's SET NULL happened in the DB,
    # invisible to the ORM's identity map until attributes are re-fetched

    remaining = db_session.scalars(select(CheckoutItem).where(CheckoutItem.id == item.id)).first()
    assert remaining is not None
    assert remaining.product_id is None
    assert remaining.product_name == product.name
