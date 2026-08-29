import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commerce.transaction.models import AuditEvent, Transaction


@pytest.fixture
def transaction(db_session: Session) -> Transaction:
    obj = Transaction(state="discovered")
    db_session.add(obj)
    db_session.flush()
    db_session.refresh(obj)
    return obj


def test_audit_event_actor_type_must_be_a_known_value(
    db_session: Session, transaction: Transaction
) -> None:
    db_session.add(
        AuditEvent(
            transaction_id=transaction.id,
            from_state=None,
            to_state="discovered",
            actor_type="bogus",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_audit_event_defaults_and_metadata_round_trip(
    db_session: Session, transaction: Transaction
) -> None:
    event = AuditEvent(
        transaction_id=transaction.id,
        from_state=None,
        to_state="discovered",
        actor_type="system",
        event_metadata={"cart_id": "abc-123"},
    )
    db_session.add(event)
    db_session.flush()
    db_session.refresh(event)

    assert event.actor_id is None
    assert event.reason is None
    assert event.event_metadata == {"cart_id": "abc-123"}
    assert event.sequence is not None
    assert event.created_at is not None


def test_audit_event_sequence_is_unique_and_increasing(
    db_session: Session, transaction: Transaction
) -> None:
    first = AuditEvent(
        transaction_id=transaction.id, from_state=None, to_state="discovered", actor_type="system"
    )
    second = AuditEvent(
        transaction_id=transaction.id,
        from_state="discovered",
        to_state="cart_created",
        actor_type="system",
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.refresh(first)
    db_session.refresh(second)

    assert second.sequence > first.sequence


def test_deleting_transaction_with_audit_events_is_restricted(
    db_session: Session, transaction: Transaction
) -> None:
    from sqlalchemy import delete

    db_session.add(
        AuditEvent(
            transaction_id=transaction.id,
            from_state=None,
            to_state="discovered",
            actor_type="system",
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Transaction).where(Transaction.id == transaction.id))
        db_session.flush()
