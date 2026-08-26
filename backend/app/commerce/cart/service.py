"""Cart business rules.

Every cart mutation goes through here — never through the router directly
and never through Gemini. Availability is checked when an item is *added*;
it is deliberately not re-checked on every quantity update (see
`docs/decisions/0005-cart-price-snapshot.md`) — checkout is what
revalidates a cart against current catalog state before anything is
finalized.
"""

import uuid

from sqlalchemy.orm import Session

from app.catalog import repository as catalog_repository
from app.commerce.cart import repository as cart_repository
from app.commerce.cart.models import Cart, CartItem
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


def create_cart(db: Session, *, merchant_id: uuid.UUID) -> Cart:
    merchant = catalog_repository.get_merchant_by_id(db, merchant_id)
    if merchant is None:
        raise MerchantNotFoundError(f"No merchant found with id '{merchant_id}'.")

    cart = Cart(merchant_id=merchant_id)
    db.add(cart)
    db.flush()
    db.refresh(cart)
    return cart


def get_cart(db: Session, cart_id: uuid.UUID) -> Cart:
    cart = cart_repository.get_cart_by_id(db, cart_id)
    if cart is None:
        raise CartNotFoundError(f"No cart found with id '{cart_id}'.")
    return cart


def add_item(db: Session, *, cart_id: uuid.UUID, product_id: uuid.UUID, quantity: int) -> Cart:
    cart = get_cart(db, cart_id)
    _validate_quantity(quantity)

    product = catalog_repository.get_product_by_id(db, product_id)
    if product is None:
        raise ProductNotFoundError(f"No product found with id '{product_id}'.")
    if product.merchant_id != cart.merchant_id:
        raise MerchantMismatchError(
            f"Product '{product_id}' belongs to a different merchant than this cart."
        )
    if not product.is_available:
        raise ProductUnavailableError(
            f"Product '{product_id}' is not currently available.", product_ids=[product_id]
        )
    if cart.currency is not None and cart.currency != product.currency:
        raise CurrencyMismatchError(
            f"This cart is already using {cart.currency}; product '{product_id}' is "
            f"priced in {product.currency}."
        )

    existing = cart_repository.get_cart_item_by_product(db, cart_id=cart.id, product_id=product.id)
    if existing is not None:
        # Adding a product already in the cart merges into the existing line
        # item (increments quantity) rather than erroring — the unit price
        # snapshot from when it was first added is kept as-is.
        existing.quantity += quantity
    else:
        db.add(
            CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=quantity,
                unit_price_minor_units=product.price_minor_units,
            )
        )
        if cart.currency is None:
            cart.currency = product.currency

    db.flush()
    db.refresh(cart)
    return cart


def update_item_quantity(
    db: Session, *, cart_id: uuid.UUID, item_id: uuid.UUID, quantity: int
) -> Cart:
    cart = get_cart(db, cart_id)
    _validate_quantity(quantity)

    item = cart_repository.get_cart_item_by_id(db, cart_id=cart.id, item_id=item_id)
    if item is None:
        raise CartItemNotFoundError(f"No item '{item_id}' found in cart '{cart_id}'.")

    item.quantity = quantity
    db.flush()
    db.refresh(cart)
    return cart


def remove_item(db: Session, *, cart_id: uuid.UUID, item_id: uuid.UUID) -> Cart:
    cart = get_cart(db, cart_id)

    item = cart_repository.get_cart_item_by_id(db, cart_id=cart.id, item_id=item_id)
    if item is None:
        raise CartItemNotFoundError(f"No item '{item_id}' found in cart '{cart_id}'.")

    db.delete(item)
    db.flush()
    db.refresh(cart)

    if not cart.items:
        cart.currency = None
        db.flush()

    return cart


def _validate_quantity(quantity: int) -> None:
    if quantity <= 0:
        raise InvalidQuantityError(f"Quantity must be positive, got {quantity}.")
