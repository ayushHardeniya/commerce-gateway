"""add transaction_audit_events table

Revision ID: c7d4e8f1a6b2
Revises: b3f1a9c02d4e
Create Date: 2026-09-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d4e8f1a6b2"
down_revision: str | Sequence[str] | None = "b3f1a9c02d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "transaction_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "sequence",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("from_state", sa.String(length=30), nullable=True),
        sa.Column("to_state", sa.String(length=30), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'agent')",
            name="ck_transaction_audit_events_actor_type_valid",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence", name="uq_transaction_audit_events_sequence"),
    )
    op.create_index(
        op.f("ix_transaction_audit_events_sequence"),
        "transaction_audit_events",
        ["sequence"],
        unique=True,
    )
    op.create_index(
        op.f("ix_transaction_audit_events_transaction_id"),
        "transaction_audit_events",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_transaction_audit_events_transaction_id"),
        table_name="transaction_audit_events",
    )
    op.drop_index(
        op.f("ix_transaction_audit_events_sequence"), table_name="transaction_audit_events"
    )
    op.drop_table("transaction_audit_events")
