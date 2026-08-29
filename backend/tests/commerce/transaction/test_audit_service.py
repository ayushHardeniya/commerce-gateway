import inspect

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    InvalidTransactionTransitionError,
    TransactionInputMismatchError,
)
from app.commerce.policy import service as policy_service
from app.commerce.transaction import repository as transaction_repository
from app.commerce.transaction import service as transaction_service
from app.commerce.transaction.models import AuditEvent

# --- append-only, by construction ---


def test_audit_repository_exposes_no_update_or_delete() -> None:
    """Pins "append-only" as a structural property of the codebase, not just
    a convention: the only way to change `transaction_audit_events` through
    this module is to insert a new row."""
    names = {name for name, _ in inspect.getmembers(transaction_repository, inspect.isfunction)}
    assert not any("update" in name or "delete" in name for name in names if "audit" in name)
    assert "create_audit_event" in names
    assert "list_audit_events_for_transaction" in names


# --- create_transaction writes a creation event ---


def test_create_transaction_writes_one_creation_event(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)

    events = transaction_service.list_audit_events(db_session, transaction.id)

    assert len(events) == 1
    assert events[0].from_state is None
    assert events[0].to_state == transaction_service.STATE_DISCOVERED
    assert events[0].actor_type == transaction_service.ACTOR_SYSTEM


def test_create_transaction_records_supplied_actor(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(
        db_session, actor_type=transaction_service.ACTOR_AGENT, actor_id="buyer-session-42"
    )

    events = transaction_service.list_audit_events(db_session, transaction.id)

    assert events[0].actor_type == transaction_service.ACTOR_AGENT
    assert events[0].actor_id == "buyer-session-42"


def test_create_transaction_rejects_unknown_actor_type(db_session: Session) -> None:
    with pytest.raises(TransactionInputMismatchError):
        transaction_service.create_transaction(db_session, actor_type="bogus")


# --- transition_transaction: exactly one event per success, none on rejection ---


def test_successful_transition_creates_exactly_one_event(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)

    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CANCELLED,
        reason="buyer changed their mind",
    )

    events = transaction_service.list_audit_events(db_session, transaction.id)
    assert len(events) == 2  # creation + this transition
    assert events[-1].from_state == transaction_service.STATE_DISCOVERED
    assert events[-1].to_state == transaction_service.STATE_CANCELLED
    assert events[-1].reason == "buyer changed their mind"


def test_rejected_transition_creates_no_event(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)
    before = len(transaction_service.list_audit_events(db_session, transaction.id))

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_PAYMENT_SUCCESS,
        )

    after_events = transaction_service.list_audit_events(db_session, transaction.id)
    assert len(after_events) == before
    assert all(
        event.to_state != transaction_service.STATE_PAYMENT_SUCCESS for event in after_events
    )


def test_rejected_transition_leaves_no_row_in_the_database_at_all(db_session: Session) -> None:
    """Not just "not visible through the service" — no row was ever added to
    the session for a guard that raised, so nothing is even pending."""
    transaction = transaction_service.create_transaction(db_session)

    with pytest.raises(InvalidTransactionTransitionError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_PAYMENT_SUCCESS,
        )

    all_events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.transaction_id == transaction.id)
    ).all()
    assert len(all_events) == 1  # only the creation event


def test_transition_rejects_unknown_actor_type(db_session: Session) -> None:
    transaction = transaction_service.create_transaction(db_session)
    with pytest.raises(TransactionInputMismatchError):
        transaction_service.transition_transaction(
            db_session,
            transaction_id=transaction.id,
            to_state=transaction_service.STATE_CANCELLED,
            actor_type="bogus",
        )


# --- ordering across multiple transitions ---


def test_multiple_transitions_preserve_order(db_session: Session, checkout: Checkout) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CANCELLED,
    )

    events = transaction_service.list_audit_events(db_session, transaction.id)

    assert [e.to_state for e in events] == [
        transaction_service.STATE_CHECKOUT_CREATED,
        transaction_service.STATE_POLICY_PENDING,
        transaction_service.STATE_CANCELLED,
    ]
    # Strictly increasing — the deterministic ordering key, not insertion
    # order the caller happened to observe.
    assert [e.sequence for e in events] == sorted(e.sequence for e in events)


# --- derived vs. caller-supplied reason ---


def test_domain_derived_reason_wins_over_caller_supplied_reason(
    db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="EUR"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_DENIED,
        reason="caller's own guess, should be overridden",
    )

    events = transaction_service.list_audit_events(db_session, transaction.id)
    assert events[-1].reason == "currency_mismatch"
    assert events[-1].event_metadata is not None
    assert "policy_decision_id" in events[-1].event_metadata


def test_caller_reason_used_when_no_domain_derived_reason_exists(
    db_session: Session, checkout: Checkout
) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)

    updated = transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
        reason="beginning policy evaluation",
    )

    events = transaction_service.list_audit_events(db_session, transaction.id)
    assert events[-1].reason == "beginning policy evaluation"
    assert updated.state == transaction_service.STATE_POLICY_PENDING


# --- persistence across a session boundary ---


def test_audit_events_survive_a_new_db_session(db_session: Session, checkout: Checkout) -> None:
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )
    transaction_id = transaction.id

    db_session.expire_all()  # drop the ORM identity map's cached attributes

    reloaded = transaction_repository.list_audit_events_for_transaction(db_session, transaction_id)
    assert [e.to_state for e in reloaded] == [
        transaction_service.STATE_CHECKOUT_CREATED,
        transaction_service.STATE_POLICY_PENDING,
    ]


def test_audit_history_remains_available_after_later_transitions(
    db_session: Session, checkout: Checkout
) -> None:
    """Earlier audit rows are never touched by a later transition — the
    creation event is still exactly as it was after several more
    transitions have happened."""
    transaction = transaction_service.create_transaction(db_session, checkout_id=checkout.id)
    first_event_id = transaction_service.list_audit_events(db_session, transaction.id)[0].id

    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_POLICY_PENDING,
    )
    transaction_service.transition_transaction(
        db_session,
        transaction_id=transaction.id,
        to_state=transaction_service.STATE_CANCELLED,
    )

    events = transaction_service.list_audit_events(db_session, transaction.id)
    creation_event = next(e for e in events if e.id == first_event_id)
    assert creation_event.from_state is None
    assert creation_event.to_state == transaction_service.STATE_CHECKOUT_CREATED
    assert len(events) == 3
