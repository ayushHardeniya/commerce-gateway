"""Merchant catalog domain models.

Money is stored as an integer count of the currency's minor units (e.g. cents
for USD, paise for INR) rather than as a float or fixed-point decimal, so
comparisons, sums, and persistence are exact and never subject to
floating-point rounding error. See
docs/decisions/0002-money-as-integer-minor-units.md for the full rationale.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_merchants_name_not_blank"),
        CheckConstraint("length(trim(slug)) > 0", name="ck_merchants_slug_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    products: Mapped[list["Product"]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("merchant_id", "sku", name="uq_products_merchant_sku"),
        CheckConstraint("price_minor_units >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="ck_products_stock_non_negative"),
        CheckConstraint("char_length(currency) = 3", name="ck_products_currency_length"),
        CheckConstraint("currency = upper(currency)", name="ck_products_currency_uppercase"),
        CheckConstraint("length(trim(sku)) > 0", name="ck_products_sku_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="ck_products_name_not_blank"),
        Index("ix_products_merchant_active", "merchant_id", "active"),
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
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    merchant: Mapped["Merchant"] = relationship(back_populates="products")

    @property
    def is_available(self) -> bool:
        """Whether the product can currently be selected for purchase.

        Deterministic and derived only from stored state: the product and its
        owning merchant must both be active, and stock must be in hand.
        """
        return self.active and self.merchant.active and self.stock_quantity > 0
