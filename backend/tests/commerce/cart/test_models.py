import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product
from app.commerce.cart.models import Cart, CartItem


def test_cart_item_quantity_must_be_positive(
    db_session: Session, cart: Cart, product: Product
) -> None:
    db_session.add(
        CartItem(cart_id=cart.id, product_id=product.id, quantity=0, unit_price_minor_units=100)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cart_item_unit_price_must_be_non_negative(
    db_session: Session, cart: Cart, product: Product
) -> None:
    db_session.add(
        CartItem(cart_id=cart.id, product_id=product.id, quantity=1, unit_price_minor_units=-1)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cart_item_product_unique_per_cart(
    db_session: Session, cart: Cart, product: Product
) -> None:
    db_session.add(
        CartItem(cart_id=cart.id, product_id=product.id, quantity=1, unit_price_minor_units=100)
    )
    db_session.flush()

    db_session.add(
        CartItem(cart_id=cart.id, product_id=product.id, quantity=2, unit_price_minor_units=100)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cart_currency_must_be_three_chars(db_session: Session, merchant: Merchant) -> None:
    db_session.add(Cart(merchant_id=merchant.id, currency="US"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cart_currency_must_be_uppercase(db_session: Session, merchant: Merchant) -> None:
    db_session.add(Cart(merchant_id=merchant.id, currency="usd"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_product_cascades_to_cart_items(
    db_session: Session, cart: Cart, product: Product
) -> None:
    db_session.add(
        CartItem(cart_id=cart.id, product_id=product.id, quantity=1, unit_price_minor_units=100)
    )
    db_session.flush()

    db_session.execute(delete(Product).where(Product.id == product.id))
    db_session.flush()

    remaining = db_session.execute(select(CartItem).where(CartItem.cart_id == cart.id)).first()
    assert remaining is None
