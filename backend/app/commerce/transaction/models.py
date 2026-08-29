"""Transaction domain models.

A `Transaction` is the durable, business-level record of one commerce
attempt as it moves across discovery, cart, checkout, policy, and payment —
the same "single mutable row, updated in place" pattern `Payment` and
`MerchantPolicy` already use, not a per-step history table. The history
itself — one immutable, append-only row per successful transition — is
`AuditEvent`, written exclusively by
`app.commerce.transaction.service.create_transaction`/
`transition_transaction` in the same flush as the `Transaction` row's own
mutation. See
`docs/decisions/0008-transaction-state-machine-validated-by-domain-state.md`
(the state machine) and
`docs/decisions/0009-transaction-audit-trail-is-a-plain-append-only-table.md`
(the audit trail).

Neither model duplicates cart/checkout/policy/payment data: `Transaction`
holds only references (`cart_id`/`checkout_id`, nullable, since a
transaction starts before either necessarily exists), and every other
domain fact — whether policy allowed the checkout, whether a payment
succeeded — is read live from those tables by
`app.commerce.transaction.service` at transition time rather than copied
here. `AuditEvent.event_metadata` follows the same discipline: small,
transition-specific facts not already on the `Transaction` row (a policy
decision id, a payment id, a failure code) — never a copy of the checkout,
payment, or catalog records those facts point to.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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


# The two known event sources: deterministic application/system code, or a
# request whose caller identified itself as acting on behalf of the AI
# buyer. There is no third category and no authentication behind either —
# see the ADR for why that's deliberately as far as this goes.
AUDIT_ACTOR_TYPES = ("system", "agent")


class AuditEvent(Base):
    """One immutable row per successful `Transaction` state transition
    (including the transaction's own creation, recorded as a transition
    from no previous state). Rows are only ever inserted — nothing in this
    codebase updates or deletes one; see `app.commerce.transaction.service`,
    the only writer.
    """

    __tablename__ = "transaction_audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('system', 'agent')",
            name="ck_transaction_audit_events_actor_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # A UUID primary key has no order of its own (uuid4 is random) — this is
    # the deterministic, gap-tolerant ordering key `GET .../audit-events`
    # sorts by, generated by the database itself (`GENERATED BY DEFAULT AS
    # IDENTITY`) rather than computed in application code, so ordering is
    # correct even under concurrent writers.
    sequence: Mapped[int] = mapped_column(
        BigInteger, Identity(), nullable=False, unique=True, index=True
    )
    # RESTRICT: an audit row must never be able to silently disappear
    # because the transaction it explains was removed — same reasoning
    # `Payment.checkout_id` already applies.
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Null only for the transaction's own creation event — every other
    # event's `from_state` is the state the transition guard matched
    # against.
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    # Free-form and optional (e.g. an API caller's own request id) — not an
    # identity/authentication system, just an attribution breadcrumb.
    actor_id: Mapped[str | None] = mapped_column(String(200))
    # The domain-derived reason where one exists (a policy denial reason, a
    # payment failure code, "checkout_expired") — see
    # `app.commerce.transaction.service._audit_reason`; otherwise whatever a
    # caller explicitly supplied.
    reason: Mapped[str | None] = mapped_column(String(500))
    event_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
