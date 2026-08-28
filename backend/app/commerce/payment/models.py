"""Payment domain models.

A `Payment` is the durable, one-row-per-checkout record of an attempt to pay
a checkout through `app.commerce.payment.provider.PaymentProvider` — the
same "single mutable row, updated in place rather than duplicated" pattern
`MerchantPolicy` already uses (see
`docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`). Its
`amount_minor_units`/`currency` are copied from the checkout's own
authoritative total at creation time and never taken from a caller — see
`app.commerce.payment.service`.

A failed attempt can be retried: `provider_order_id` is updated in place and
`status` moves back to `created` rather than inserting a second row, so a
checkout can never end up with two live payment attempts at once. The
`checkout_id` uniqueness constraint is what makes "at most one successful
payment per checkout" a database-level guarantee, not just an application
check.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("checkout_id", name="uq_payments_checkout"),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        CheckConstraint(
            "status IN ('created', 'success', 'failed')", name="ck_payments_status_valid"
        ),
        CheckConstraint("amount_minor_units >= 0", name="ck_payments_amount_non_negative"),
        CheckConstraint("char_length(currency) = 3", name="ck_payments_currency_length"),
        CheckConstraint("currency = upper(currency)", name="ck_payments_currency_uppercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # RESTRICT, not CASCADE: a payment is a durable record of a purchase
    # attempt — the same reasoning `Checkout.cart_id` already applies to its
    # own cart (see `app.commerce.checkout.models`).
    checkout_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("checkouts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100))
    # The checkout's authoritative total/currency at the moment payment was
    # last (re)initiated — never a value a caller supplies. See
    # `app.commerce.payment.service.initiate_payment`.
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
