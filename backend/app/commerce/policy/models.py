"""Policy and authorization domain models.

`MerchantPolicy` is a single mutable row per merchant (`version` increments
on every update) rather than a history table — see
`docs/decisions/0006-policy-snapshot-and-explicit-authorization.md` for why
that's still safe: `PolicyDecision` copies the exact limit/currency/version
that governed it at evaluation time onto itself, so a later policy edit can
never retroactively change what an already-made decision meant.

`CheckoutAuthorization` is the explicit, one-time human approval record for
a `PolicyDecision` that came back REQUIRE_AUTHORIZATION. Its existence for a
given checkout *is* the "AUTHORIZED" state — there is no separate status
column to drift out of sync with it.
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MerchantPolicy(Base):
    __tablename__ = "merchant_policies"
    __table_args__ = (
        UniqueConstraint("merchant_id", name="uq_merchant_policies_merchant"),
        CheckConstraint("version > 0", name="ck_merchant_policies_version_positive"),
        CheckConstraint(
            "autonomous_limit_minor_units >= 0", name="ck_merchant_policies_limit_non_negative"
        ),
        CheckConstraint("char_length(currency) = 3", name="ck_merchant_policies_currency_length"),
        CheckConstraint(
            "currency = upper(currency)", name="ck_merchant_policies_currency_uppercase"
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    autonomous_limit_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PolicyDecision(Base):
    """One deterministic evaluation of a checkout against the policy that
    governed it at that moment. Immutable once created — `evaluate_checkout`
    returns the existing row for a checkout rather than ever overwriting it.
    """

    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint("checkout_id", name="uq_policy_decisions_checkout"),
        CheckConstraint(
            "decision IN ('allow', 'require_authorization', 'deny')",
            name="ck_policy_decisions_decision_valid",
        ),
        CheckConstraint("amount_minor_units >= 0", name="ck_policy_decisions_amount_non_negative"),
        CheckConstraint(
            "autonomous_limit_minor_units >= 0",
            name="ck_policy_decisions_limit_non_negative",
        ),
        CheckConstraint(
            "policy_version >= 0", name="ck_policy_decisions_policy_version_non_negative"
        ),
        CheckConstraint("char_length(currency) = 3", name="ck_policy_decisions_currency_length"),
        CheckConstraint(
            "currency = upper(currency)", name="ck_policy_decisions_currency_uppercase"
        ),
        CheckConstraint(
            "char_length(policy_currency) = 3", name="ck_policy_decisions_policy_currency_length"
        ),
        CheckConstraint(
            "policy_currency = upper(policy_currency)",
            name="ck_policy_decisions_policy_currency_uppercase",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # RESTRICT: a decision is a durable record of what was decided and why —
    # it must never silently disappear because the checkout it governed was
    # removed, the same reasoning `Checkout.cart_id` already applies.
    checkout_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("checkouts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Nullable: null means no explicit `MerchantPolicy` row existed and the
    # safe default was applied (see `policy_version` below).
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("merchant_policies.id", ondelete="SET NULL"),
    )
    # 0 is reserved to mean "the safe default was applied, no explicit
    # MerchantPolicy existed for this merchant yet" — never a version a real
    # MerchantPolicy row can have (`version > 0` there).
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    autonomous_limit_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    # The checkout's authoritative total/currency at evaluation time — never
    # a value supplied by a caller (see `app.commerce.policy.service`).
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CheckoutAuthorization(Base):
    """The one-time human approval of a `PolicyDecision`. Its presence for a
    checkout is definitionally what "AUTHORIZED" means — it is never
    confused with, or mistaken for, payment having occurred."""

    __tablename__ = "checkout_authorizations"
    __table_args__ = (
        UniqueConstraint("checkout_id", name="uq_checkout_authorizations_checkout"),
        UniqueConstraint("policy_decision_id", name="uq_checkout_authorizations_policy_decision"),
        CheckConstraint(
            "amount_minor_units >= 0", name="ck_checkout_authorizations_amount_non_negative"
        ),
        CheckConstraint(
            "char_length(currency) = 3", name="ck_checkout_authorizations_currency_length"
        ),
        CheckConstraint(
            "currency = upper(currency)", name="ck_checkout_authorizations_currency_uppercase"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checkout_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("checkouts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    policy_decision_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("policy_decisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # The exact amount/currency a human approved — re-checked against the
    # checkout's authoritative total at authorization time, never trusted as
    # given (see `app.commerce.policy.service.authorize_checkout`).
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
