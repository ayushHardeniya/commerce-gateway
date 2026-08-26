"""Checkout domain models.

A `Checkout` is an immutable snapshot of a cart "frozen" for purchase: its
total and currency are computed once at creation time
(`app.commerce.checkout.service.create_checkout`) and never recomputed from
the live cart afterward. Its line items (`CheckoutItem`) denormalize product
identity (name, sku, price) rather than relying solely on a live FK, so a
checkout stays a complete, readable record even if the underlying product is
later changed or deleted — see `docs/decisions/0005-cart-price-snapshot.md`.

`status` only ever stores "active", "completed", or "cancelled" — "expired"
is deliberately never written to the column. It's a derived condition
(`Checkout.effective_status`), the same pattern already used for
`Product.is_available`: a fact computed from stored state, not tracked as
separate mutable state that could drift out of sync.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Checkout(Base):
    __tablename__ = "checkouts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')", name="ck_checkouts_status_valid"
        ),
        CheckConstraint("total_minor_units >= 0", name="ck_checkouts_total_non_negative"),
        CheckConstraint("char_length(currency) = 3", name="ck_checkouts_currency_length"),
        CheckConstraint("currency = upper(currency)", name="ck_checkouts_currency_uppercase"),
        CheckConstraint("expires_at > created_at", name="ck_checkouts_expires_after_created"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # RESTRICT, not CASCADE: a checkout is meant to be a durable record of a
    # purchase attempt. Deleting its cart (e.g. via the merchant hard-delete
    # cascade from docs/decisions/0003) must fail loudly rather than quietly
    # destroy the checkout — the opposite of how cart_items relate to carts.
    cart_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    total_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list["CheckoutItem"]] = relationship(
        back_populates="checkout",
        cascade="all, delete-orphan",
        order_by="CheckoutItem.created_at",
    )

    @property
    def effective_status(self) -> str:
        """The status callers should actually treat as true: "active" flips
        to "expired" once `expires_at` has passed, without anything having
        to write that transition to the database."""
        if self.status == "active" and datetime.now(UTC) >= self.expires_at:
            return "expired"
        return self.status


class CheckoutItem(Base):
    __tablename__ = "checkout_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_checkout_items_quantity_positive"),
        CheckConstraint(
            "unit_price_minor_units >= 0", name="ck_checkout_items_unit_price_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checkout_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("checkouts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL, not a hard requirement: this row's own denormalized columns
    # (name/sku/price below) are what make the checkout durable. The FK is
    # kept only as a best-effort live link back to the catalog, not as the
    # source of truth for what was actually purchased.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    checkout: Mapped["Checkout"] = relationship(back_populates="items")

    @property
    def subtotal_minor_units(self) -> int:
        return self.unit_price_minor_units * self.quantity
