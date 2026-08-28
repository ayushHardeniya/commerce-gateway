"""add transactions table

Revision ID: b3f1a9c02d4e
Revises: aa1488d688c7
Create Date: 2026-09-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f1a9c02d4e"
down_revision: str | Sequence[str] | None = "aa1488d688c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSACTION_STATES = (
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


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("cart_id", sa.UUID(), nullable=True),
        sa.Column("checkout_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN (" + ", ".join(f"'{state}'" for state in _TRANSACTION_STATES) + ")",
            name="ck_transactions_state_valid",
        ),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checkout_id"], ["checkouts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkout_id", name="uq_transactions_checkout"),
    )
    op.create_index(op.f("ix_transactions_cart_id"), "transactions", ["cart_id"], unique=False)
    op.create_index(
        op.f("ix_transactions_checkout_id"), "transactions", ["checkout_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_transactions_checkout_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_cart_id"), table_name="transactions")
    op.drop_table("transactions")
