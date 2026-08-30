"""Read/write access to the transactions and transaction_audit_events
tables. No business rules here — see `app.commerce.transaction.service`.

There is deliberately no `update_audit_event`/`delete_audit_event` function
here: `create_audit_event` is the only write this module offers for
`AuditEvent`, which is what makes "audit events are append-only" true in
practice rather than just documented — the same enforced-by-omission
pattern `app.commerce.policy` already uses for `PolicyDecision`.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.commerce.transaction.models import AuditEvent, Transaction


def get_transaction_by_id(db: Session, transaction_id: uuid.UUID) -> Transaction | None:
    stmt = select(Transaction).where(Transaction.id == transaction_id)
    return db.scalars(stmt).first()


def get_transaction_by_checkout(db: Session, checkout_id: uuid.UUID) -> Transaction | None:
    stmt = select(Transaction).where(Transaction.checkout_id == checkout_id)
    return db.scalars(stmt).first()


def list_transactions(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[list[Transaction], int]:
    """Newest first, ordered by `Transaction.sequence` (the database-
    generated identity column) rather than `created_at` — see the model's
    own comment for why `created_at` alone isn't a reliable order."""
    total = db.scalar(select(func.count()).select_from(Transaction)) or 0

    items = list(
        db.scalars(
            select(Transaction).order_by(Transaction.sequence.desc()).limit(limit).offset(offset)
        ).all()
    )
    return items, total


def create_audit_event(
    db: Session,
    *,
    transaction_id: uuid.UUID,
    from_state: str | None,
    to_state: str,
    actor_type: str,
    actor_id: str | None,
    reason: str | None,
    event_metadata: dict | None,
) -> AuditEvent:
    event = AuditEvent(
        transaction_id=transaction_id,
        from_state=from_state,
        to_state=to_state,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        event_metadata=event_metadata,
    )
    db.add(event)
    return event


def list_audit_events_for_transaction(db: Session, transaction_id: uuid.UUID) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.transaction_id == transaction_id)
        .order_by(AuditEvent.sequence.asc())
    )
    return list(db.scalars(stmt).all())
