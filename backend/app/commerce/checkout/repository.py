"""Read/write access to the checkout tables. No business rules here — see
`app.commerce.checkout.service`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.commerce.checkout.models import Checkout


def get_checkout_by_id(db: Session, checkout_id: uuid.UUID) -> Checkout | None:
    stmt = select(Checkout).options(joinedload(Checkout.items)).where(Checkout.id == checkout_id)
    return db.scalars(stmt).unique().first()


def get_active_checkout_for_cart(db: Session, cart_id: uuid.UUID) -> Checkout | None:
    """The cart's currently-active (not expired/completed/cancelled) checkout,
    if any — used to block creating a second simultaneous checkout for the
    same cart."""
    stmt = select(Checkout).where(
        Checkout.cart_id == cart_id,
        Checkout.status == "active",
        Checkout.expires_at > datetime.now(UTC),
    )
    return db.scalars(stmt).first()
