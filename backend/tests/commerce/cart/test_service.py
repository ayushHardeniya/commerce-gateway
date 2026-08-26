import uuid

import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product
from app.commerce.cart import service
from app.commerce.cart.models import Cart
from app.commerce.errors import (
    CartItemNotFoundError,
    CartNotFoundError,
    CurrencyMismatchError,
    InvalidQuantityError,
    MerchantMismatchError,
    MerchantNotFoundError,
    ProductNotFoundError,
    ProductUnavailableError,
)

# --- create / retrieve ---


def test_create_cart(db_session: Session, merchant: Merchant) -> None:
    cart = service.create_cart(db_session, merchant_id=merchant.id)

    assert cart.merchant_id == merchant.id
    assert cart.currency is None
    assert cart.items == []


def test_create_cart_for_missing_merchant_raises(db_session: Session) -> None:
    with pytest.raises(MerchantNotFoundError):
        service.create_cart(db_session, merchant_id=uuid.uuid4())


def test_get_cart(db_session: Session, cart: Cart) -> None:
    fetched = service.get_cart(db_session, cart.id)

    assert fetched.id == cart.id


def test_get_missing_cart_raises(db_session: Session) -> None:
    with pytest.raises(CartNotFoundError):
        service.get_cart(db_session, uuid.uuid4())


# --- add item ---


def test_add_item(db_session: Session, cart: Cart, product: Product) -> None:
    updated = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=2)

    assert len(updated.items) == 1
    item = updated.items[0]
    assert item.product_id == product.id
    assert item.quantity == 2
    assert item.unit_price_minor_units == product.price_minor_units
    assert updated.currency == product.currency


def test_add_item_missing_product_raises(db_session: Session, cart: Cart) -> None:
    with pytest.raises(ProductNotFoundError):
        service.add_item(db_session, cart_id=cart.id, product_id=uuid.uuid4(), quantity=1)


def test_add_item_missing_cart_raises(db_session: Session, product: Product) -> None:
    with pytest.raises(CartNotFoundError):
        service.add_item(db_session, cart_id=uuid.uuid4(), product_id=product.id, quantity=1)


@pytest.mark.parametrize("quantity", [0, -1])
def test_add_item_invalid_quantity_raises(
    db_session: Session, cart: Cart, product: Product, quantity: int
) -> None:
    with pytest.raises(InvalidQuantityError):
        service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=quantity)


def test_add_item_inactive_product_raises(
    db_session: Session, cart: Cart, product: Product
) -> None:
    product.active = False
    db_session.flush()

    with pytest.raises(ProductUnavailableError):
        service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)


def test_add_item_out_of_stock_product_raises(
    db_session: Session, cart: Cart, product: Product
) -> None:
    product.stock_quantity = 0
    db_session.flush()

    with pytest.raises(ProductUnavailableError):
        service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)


def test_add_item_from_different_merchant_raises(
    db_session: Session, cart: Cart, other_merchant: Merchant
) -> None:
    other_product = Product(
        merchant_id=other_merchant.id,
        sku="OTHER-1",
        name="Other product",
        price_minor_units=500,
        currency="USD",
        stock_quantity=5,
    )
    db_session.add(other_product)
    db_session.flush()

    with pytest.raises(MerchantMismatchError):
        service.add_item(db_session, cart_id=cart.id, product_id=other_product.id, quantity=1)


def test_add_item_currency_mismatch_raises(
    db_session: Session, cart: Cart, merchant: Merchant, product: Product
) -> None:
    service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)

    inr_product = Product(
        merchant_id=merchant.id,
        sku="ACME-INR",
        name="Rupee product",
        price_minor_units=100,
        currency="INR",
        stock_quantity=5,
    )
    db_session.add(inr_product)
    db_session.flush()

    with pytest.raises(CurrencyMismatchError):
        service.add_item(db_session, cart_id=cart.id, product_id=inr_product.id, quantity=1)


def test_add_item_duplicate_product_merges_quantity(
    db_session: Session, cart: Cart, product: Product
) -> None:
    service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=2)
    updated = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=3)

    assert len(updated.items) == 1
    assert updated.items[0].quantity == 5


def test_add_item_duplicate_product_keeps_original_price_snapshot(
    db_session: Session, cart: Cart, product: Product
) -> None:
    service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)

    product.price_minor_units = 9999
    db_session.flush()

    updated = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)

    assert updated.items[0].unit_price_minor_units == 1000


# --- update quantity ---


def test_update_item_quantity(db_session: Session, cart: Cart, product: Product) -> None:
    added = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)
    item_id = added.items[0].id

    updated = service.update_item_quantity(db_session, cart_id=cart.id, item_id=item_id, quantity=7)

    assert updated.items[0].quantity == 7


@pytest.mark.parametrize("quantity", [0, -3])
def test_update_item_quantity_invalid_raises(
    db_session: Session, cart: Cart, product: Product, quantity: int
) -> None:
    added = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)
    item_id = added.items[0].id

    with pytest.raises(InvalidQuantityError):
        service.update_item_quantity(
            db_session, cart_id=cart.id, item_id=item_id, quantity=quantity
        )


def test_update_item_quantity_missing_item_raises(db_session: Session, cart: Cart) -> None:
    with pytest.raises(CartItemNotFoundError):
        service.update_item_quantity(db_session, cart_id=cart.id, item_id=uuid.uuid4(), quantity=1)


def test_update_item_quantity_does_not_revalidate_availability(
    db_session: Session, cart: Cart, product: Product
) -> None:
    """Availability is checked when an item is added, not on every quantity
    update — checkout is what revalidates against live catalog state."""
    added = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)
    item_id = added.items[0].id

    product.stock_quantity = 0
    db_session.flush()

    updated = service.update_item_quantity(db_session, cart_id=cart.id, item_id=item_id, quantity=2)

    assert updated.items[0].quantity == 2


# --- remove item ---


def test_remove_item(db_session: Session, cart: Cart, product: Product) -> None:
    added = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)
    item_id = added.items[0].id

    updated = service.remove_item(db_session, cart_id=cart.id, item_id=item_id)

    assert updated.items == []


def test_remove_last_item_resets_currency(
    db_session: Session, cart: Cart, product: Product
) -> None:
    added = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=1)
    assert added.currency == "USD"

    updated = service.remove_item(db_session, cart_id=cart.id, item_id=added.items[0].id)

    assert updated.currency is None


def test_remove_missing_item_raises(db_session: Session, cart: Cart) -> None:
    with pytest.raises(CartItemNotFoundError):
        service.remove_item(db_session, cart_id=cart.id, item_id=uuid.uuid4())


# --- deterministic subtotal ---


def test_subtotal_is_deterministic_sum_of_unit_price_times_quantity(
    db_session: Session, cart: Cart, product: Product, second_product: Product
) -> None:
    service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=3)
    updated = service.add_item(
        db_session, cart_id=cart.id, product_id=second_product.id, quantity=2
    )

    expected = product.price_minor_units * 3 + second_product.price_minor_units * 2
    assert updated.subtotal_minor_units == expected


def test_subtotal_uses_snapshotted_price_not_current_price(
    db_session: Session, cart: Cart, product: Product
) -> None:
    updated = service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=2)
    snapshot_price = updated.items[0].unit_price_minor_units

    product.price_minor_units = snapshot_price + 500
    db_session.flush()

    refetched = service.get_cart(db_session, cart.id)
    assert refetched.subtotal_minor_units == snapshot_price * 2
