"""Proves the merchant->product cascade is enforced by the database itself.

`Merchant.products` also declares `cascade="all, delete-orphan"` at the ORM
level, but that only fires when SQLAlchemy loads and deletes objects through
the ORM's unit-of-work. Deleting via a Core `delete()` statement bypasses that
entirely — the only thing that can remove the product rows here is the
`ON DELETE CASCADE` foreign key constraint from the migration.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product


def test_deleting_merchant_cascades_to_products_via_db_constraint(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    product_id = product.id

    db_session.execute(delete(Merchant).where(Merchant.id == merchant.id))
    db_session.flush()

    remaining = db_session.execute(select(Product).where(Product.id == product_id)).first()
    assert remaining is None
