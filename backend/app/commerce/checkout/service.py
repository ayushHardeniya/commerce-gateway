"""Checkout business rules.

`create_checkout` is the one place a cart's price snapshot gets
revalidated against live catalog state before anything is frozen into a
purchasable total — see `docs/decisions/0005-cart-price-snapshot.md`. No
payment, authorization, or policy check happens here or anywhere else in
this milestone; a checkout is only ever preparation for one.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.commerce.cart import service as cart_service
from app.commerce.cart.models import Cart
from app.commerce.checkout import repository as checkout_repository
from app.commerce.checkout.models import Checkout, CheckoutItem
from app.commerce.errors import (
    CheckoutNotFoundError,
    EmptyCartError,
    InvalidCartStateError,
    PriceChange,
    PriceChangedError,
    ProductUnavailableError,
)

CHECKOUT_EXPIRY = timedelta(minutes=15)


def create_checkout(db: Session, *, cart_id: uuid.UUID) -> Checkout:
    cart = cart_service.get_cart(db, cart_id)

    existing_active = checkout_repository.get_active_checkout_for_cart(db, cart_id=cart.id)
    if existing_active is not None:
        raise InvalidCartStateError(
            f"Cart '{cart_id}' already has an active checkout ('{existing_active.id}')."
        )

    if not cart.items:
        raise EmptyCartError(f"Cart '{cart_id}' is empty; nothing to check out.")

    _ensure_products_available(cart)
    _ensure_prices_unchanged(cart)

    total = cart.subtotal_minor_units
    now = datetime.now(UTC)
    checkout = Checkout(
        cart_id=cart.id,
        status="active",
        total_minor_units=total,
        currency=cart.currency,
        created_at=now,
        expires_at=now + CHECKOUT_EXPIRY,
    )
    db.add(checkout)
    db.flush()

    for item in cart.items:
        db.add(
            CheckoutItem(
                checkout_id=checkout.id,
                product_id=item.product_id,
                product_name=item.product.name,
                product_sku=item.product.sku,
                quantity=item.quantity,
                unit_price_minor_units=item.unit_price_minor_units,
            )
        )

    db.flush()
    db.refresh(checkout)
    return checkout


def get_checkout(db: Session, checkout_id: uuid.UUID) -> Checkout:
    checkout = checkout_repository.get_checkout_by_id(db, checkout_id)
    if checkout is None:
        raise CheckoutNotFoundError(f"No checkout found with id '{checkout_id}'.")
    return checkout


def _ensure_products_available(cart: Cart) -> None:
    unavailable_ids = [item.product_id for item in cart.items if not item.product.is_available]
    if unavailable_ids:
        raise ProductUnavailableError(
            "One or more products in this cart are no longer available.",
            product_ids=unavailable_ids,
        )


def _ensure_prices_unchanged(cart: Cart) -> None:
    changes = [
        PriceChange(
            product_id=item.product_id,
            previous_unit_price_minor_units=item.unit_price_minor_units,
            current_unit_price_minor_units=item.product.price_minor_units,
        )
        for item in cart.items
        if item.product.price_minor_units != item.unit_price_minor_units
    ]
    if changes:
        raise PriceChangedError(
            "The price of one or more products has changed since being added to the cart.",
            changes=changes,
        )
