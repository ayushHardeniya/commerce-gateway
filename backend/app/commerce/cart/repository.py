"""Read/write access to the cart tables.

Plain functions over a `Session`, same style as `app.catalog.repository`:
no business rules here, only queries. Business rules (availability,
quantity validation, price snapshotting) live in `app.commerce.cart.service`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.catalog.models import Product
from app.commerce.cart.models import Cart, CartItem


def get_cart_by_id(db: Session, cart_id: uuid.UUID) -> Cart | None:
    stmt = (
        select(Cart)
        .options(joinedload(Cart.items).joinedload(CartItem.product).joinedload(Product.merchant))
        .where(Cart.id == cart_id)
    )
    return db.scalars(stmt).unique().first()


def get_cart_item_by_id(db: Session, *, cart_id: uuid.UUID, item_id: uuid.UUID) -> CartItem | None:
    stmt = select(CartItem).where(CartItem.cart_id == cart_id, CartItem.id == item_id)
    return db.scalars(stmt).first()


def get_cart_item_by_product(
    db: Session, *, cart_id: uuid.UUID, product_id: uuid.UUID
) -> CartItem | None:
    stmt = select(CartItem).where(CartItem.cart_id == cart_id, CartItem.product_id == product_id)
    return db.scalars(stmt).first()
