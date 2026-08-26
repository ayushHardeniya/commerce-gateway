"""Cart domain models.

A cart belongs to exactly one merchant and holds line items that reference
products by id rather than copying mutable product state. Each line item
snapshots the unit price in effect when it was added
(`unit_price_minor_units`) — the product's *current* price can move
independently afterward; see `docs/decisions/0005-cart-price-snapshot.md`
for why, and `app.commerce.checkout.service` for where that snapshot gets
revalidated against live catalog state.

Money is stored as integer minor units, matching
`docs/decisions/0002-money-as-integer-minor-units.md`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.catalog.models import Product
from app.db.session import Base


class Cart(Base):
    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(
            "currency IS NULL OR char_length(currency) = 3", name="ck_carts_currency_length"
        ),
        CheckConstraint(
            "currency IS NULL OR currency = upper(currency)", name="ck_carts_currency_uppercase"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str | None] = mapped_column(
        String(3),
        doc="Set from the first item added; every later item must match it. "
        "Null while the cart is empty.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartItem.created_at",
    )

    @property
    def subtotal_minor_units(self) -> int:
        """sum(unit_price_minor_units × quantity) — the single deterministic
        definition of a cart's subtotal. Never recomputed differently
        elsewhere (checkout totals derive from this same arithmetic)."""
        return sum(item.subtotal_minor_units for item in self.items)


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
        CheckConstraint(
            "unit_price_minor_units >= 0", name="ck_cart_items_unit_price_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cart_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Cascades with the product: a cart is ephemeral pre-purchase state, so
    # if a product is deleted there is nothing left to buy and no reason to
    # keep the line item. Contrast with `CheckoutItem`, which snapshots
    # product identity precisely so a *checkout* survives product deletion.
    product_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    cart: Mapped["Cart"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    @property
    def subtotal_minor_units(self) -> int:
        return self.unit_price_minor_units * self.quantity
