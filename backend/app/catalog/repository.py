"""Read/write access to the merchant catalog tables.

Kept as plain functions over a `Session` rather than a class: the queries
here are simple and don't carry state between calls, so a repository class
would only add ceremony.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.catalog.models import Merchant, Product


def list_merchants(db: Session, *, active_only: bool = True) -> list[Merchant]:
    stmt = select(Merchant).order_by(Merchant.name)
    if active_only:
        stmt = stmt.where(Merchant.active.is_(True))
    return list(db.scalars(stmt))


def get_merchant_by_slug(db: Session, slug: str) -> Merchant | None:
    stmt = select(Merchant).where(Merchant.slug == slug)
    return db.scalars(stmt).first()


def get_merchant_by_id(db: Session, merchant_id: uuid.UUID) -> Merchant | None:
    return db.get(Merchant, merchant_id)


def get_product_by_id(db: Session, product_id: uuid.UUID) -> Product | None:
    stmt = select(Product).options(joinedload(Product.merchant)).where(Product.id == product_id)
    return db.scalars(stmt).first()


def search_products(
    db: Session,
    *,
    merchant_id: uuid.UUID | None = None,
    query: str | None = None,
    active_only: bool = True,
    in_stock_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Product], int]:
    """Search products, optionally scoped to a merchant, with a total match count.

    `merchant_id=None` searches across every merchant — the global catalog
    discovery entry point used by `GET /api/catalog/products`.
    """
    conditions = []
    if merchant_id is not None:
        conditions.append(Product.merchant_id == merchant_id)
    if active_only:
        conditions.append(Product.active.is_(True))
    if in_stock_only:
        conditions.append(Product.stock_quantity > 0)
    if query:
        conditions.append(Product.name.ilike(f"%{query}%"))

    total = db.scalar(select(func.count()).select_from(Product).where(*conditions)) or 0

    items = list(
        db.scalars(
            select(Product)
            .options(joinedload(Product.merchant))
            .where(*conditions)
            .order_by(Product.name)
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total
