"""Transaction domain model.

A `Transaction` is the durable, business-level record of one commerce
attempt as it moves across discovery, cart, checkout, policy, and payment —
the same "single mutable row, updated in place" pattern `Payment` and
`MerchantPolicy` already use, not a per-step history table (a full
per-transition audit trail is M6B, not M6A — see
`docs/decisions/0008-transaction-state-machine-validated-by-domain-state.md`).

It never duplicates cart/checkout/policy/payment data: `cart_id` and
`checkout_id` are references to those tables (nullable, since a transaction
starts before either necessarily exists), and every other domain fact —
whether policy allowed the checkout, whether a payment succeeded — is read
live from those tables by `app.commerce.transaction.service` at transition
time rather than copied here.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# Every state the state machine can be in. Kept here (not in schemas.py) so
# the DB CheckConstraint below and `app.commerce.transaction.service`'s
# transition table both read from one definition.
TRANSACTION_STATES = (
    "discovered",
    "cart_created",
    "checkout_created",
    "policy_pending",
    "authorized",
    "payment_pending",
    "payment_success",
    "order_confirmed",
    "policy_denied",
    "payment_failed",
    "checkout_expired",
    "cancelled",
    "failed",
)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("checkout_id", name="uq_transactions_checkout"),
        CheckConstraint(
            "state IN (" + ", ".join(f"'{state}'" for state in TRANSACTION_STATES) + ")",
            name="ck_transactions_state_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # RESTRICT, not CASCADE: a transaction is a durable record of an attempt
    # — the same reasoning `Payment.checkout_id`/`Checkout.cart_id` already
    # apply to their own references. Nullable: a transaction can exist
    # before a cart/checkout is attached to it (DISCOVERED/CART_CREATED).
    cart_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("carts.id", ondelete="RESTRICT"), index=True
    )
    checkout_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("checkouts.id", ondelete="RESTRICT"), index=True
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="discovered")
    # Set only on entering a failure/terminal-failure state (policy_denied,
    # payment_failed, checkout_expired, cancelled, failed) — never on a
    # success path.
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
