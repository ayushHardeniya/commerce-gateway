"""Transaction state machine and audit trail.

This is the deterministic boundary described in
`docs/decisions/0008-transaction-state-machine-validated-by-domain-state.md`:
the allowed `(from_state, to_state)` edges are a fixed table below, and a
transition is accepted only if that edge exists *and* — for edges backed by
a real domain fact (a policy decision, a payment's status, a checkout's
expiry) — the referenced cart/checkout/policy/payment records currently
support it. Nothing here ever accepts a caller's (or an LLM's) unverified
claim that "policy allowed this" or "payment succeeded"; it always re-reads
`app.commerce.checkout`/`policy`/`payment` state fresh, the same discipline
`app.commerce.payment.service` already applies to eligibility.

This is also the *only* place `AuditEvent` rows get written (see
`docs/decisions/0009-transaction-audit-trail-is-a-plain-append-only-table.md`):
`create_transaction` and `transition_transaction` each add exactly one
`AuditEvent` to the session in the same call that mutates the `Transaction`
row, and both go to the database in the same `flush()`/`commit()` — so a
transition and the fact that it happened are persisted atomically, and a
guard that raises (an invalid or domain-unsupported transition) never
reaches the point where an event would be added at all.

No `Tool` in `app.agents` reaches this module — enforced by omission, the
same pattern already used for payment (see
`tests/agents/test_architecture.py::test_no_transaction_tool_is_declared`).
Audit events are therefore always written by this deterministic service
code, never by (or on behalf of) an LLM's own judgment about what happened.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.commerce.cart import repository as cart_repository
from app.commerce.checkout import repository as checkout_repository
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    CartNotFoundError,
    CheckoutAlreadyHasTransactionError,
    CheckoutNotFoundError,
    InvalidTransactionTransitionError,
    TransactionInputMismatchError,
    TransactionNotFoundError,
)
from app.commerce.payment import repository as payment_repository
from app.commerce.payment.service import STATUS_CREATED as PAYMENT_STATUS_CREATED
from app.commerce.payment.service import STATUS_FAILED as PAYMENT_STATUS_FAILED
from app.commerce.payment.service import STATUS_SUCCESS as PAYMENT_STATUS_SUCCESS
from app.commerce.policy import repository as policy_repository
from app.commerce.policy.service import DECISION_ALLOW, DECISION_REQUIRE_AUTHORIZATION
from app.commerce.transaction import repository
from app.commerce.transaction.models import AuditEvent, Transaction

ACTOR_SYSTEM = "system"
ACTOR_AGENT = "agent"

STATE_DISCOVERED = "discovered"
STATE_CART_CREATED = "cart_created"
STATE_CHECKOUT_CREATED = "checkout_created"
STATE_POLICY_PENDING = "policy_pending"
STATE_AUTHORIZED = "authorized"
STATE_PAYMENT_PENDING = "payment_pending"
STATE_PAYMENT_SUCCESS = "payment_success"
STATE_ORDER_CONFIRMED = "order_confirmed"
STATE_POLICY_DENIED = "policy_denied"
STATE_PAYMENT_FAILED = "payment_failed"
STATE_CHECKOUT_EXPIRED = "checkout_expired"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"

# No transition leaves any of these — reachable only via the guard/table
# entries below, never written to directly.
TERMINAL_STATES = frozenset(
    {
        STATE_ORDER_CONFIRMED,
        STATE_POLICY_DENIED,
        STATE_CHECKOUT_EXPIRED,
        STATE_CANCELLED,
        STATE_FAILED,
    }
)

_Guard = Callable[..., dict[str, Any]]


def _require_checkout(db: Session, transaction: Transaction) -> Checkout:
    if transaction.checkout_id is None:
        raise InvalidTransactionTransitionError(
            f"Transaction '{transaction.id}' has no checkout attached yet."
        )
    checkout = checkout_repository.get_checkout_by_id(db, transaction.checkout_id)
    assert checkout is not None, (
        "Transaction.checkout_id is ON DELETE RESTRICT; it must still exist."
    )
    return checkout


def _guard_discovered_to_cart_created(
    db: Session, transaction: Transaction, *, cart_id: uuid.UUID | None, **_: Any
) -> dict[str, Any]:
    if cart_id is None:
        raise TransactionInputMismatchError(
            "cart_id is required to move a transaction to 'cart_created'."
        )
    cart = cart_repository.get_cart_by_id(db, cart_id)
    if cart is None:
        raise CartNotFoundError(f"No cart found with id '{cart_id}'.")
    return {"cart_id": cart.id}


def _guard_cart_created_to_checkout_created(
    db: Session, transaction: Transaction, *, checkout_id: uuid.UUID | None, **_: Any
) -> dict[str, Any]:
    if checkout_id is None:
        raise TransactionInputMismatchError(
            "checkout_id is required to move a transaction to 'checkout_created'."
        )
    checkout = checkout_repository.get_checkout_by_id(db, checkout_id)
    if checkout is None:
        raise CheckoutNotFoundError(f"No checkout found with id '{checkout_id}'.")
    if transaction.cart_id is not None and checkout.cart_id != transaction.cart_id:
        raise TransactionInputMismatchError(
            f"Checkout '{checkout_id}' belongs to cart '{checkout.cart_id}', not this "
            f"transaction's cart '{transaction.cart_id}'."
        )
    existing = repository.get_transaction_by_checkout(db, checkout_id)
    if existing is not None and existing.id != transaction.id:
        raise CheckoutAlreadyHasTransactionError(
            f"Checkout '{checkout_id}' is already linked to transaction '{existing.id}'."
        )
    return {"checkout_id": checkout.id, "cart_id": checkout.cart_id}


def _guard_checkout_created_to_policy_pending(
    db: Session, transaction: Transaction, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    if checkout.effective_status != "active":
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' is '{checkout.effective_status}', not active; cannot "
            "begin policy evaluation."
        )
    return {}


def _guard_any_to_checkout_expired(
    db: Session, transaction: Transaction, *, failure_reason: str | None, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    if checkout.effective_status != "expired":
        raise InvalidTransactionTransitionError(f"Checkout '{checkout.id}' has not expired.")
    return {
        "failure_reason": failure_reason or "checkout_expired",
        "metadata": {
            "checkout_id": str(checkout.id),
            "expired_at": checkout.expires_at.isoformat(),
        },
    }


def _guard_policy_pending_to_authorized(
    db: Session, transaction: Transaction, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    decision = policy_repository.get_decision_by_checkout(db, checkout.id)
    if decision is None:
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' has not been evaluated against policy yet."
        )
    if decision.decision == DECISION_ALLOW:
        return {"metadata": {"policy_decision_id": str(decision.id), "policy_decision": "allow"}}
    if decision.decision == DECISION_REQUIRE_AUTHORIZATION:
        authorization = policy_repository.get_authorization_by_checkout(db, checkout.id)
        if authorization is None:
            raise InvalidTransactionTransitionError(
                f"Checkout '{checkout.id}' requires authorization before it can be treated as "
                "authorized."
            )
        if (
            authorization.amount_minor_units != checkout.total_minor_units
            or authorization.currency != checkout.currency
        ):
            raise InvalidTransactionTransitionError(
                f"Checkout '{checkout.id}''s authorization no longer matches its current "
                "amount/currency."
            )
        return {
            "metadata": {
                "policy_decision_id": str(decision.id),
                "policy_decision": "require_authorization",
                "authorization_id": str(authorization.id),
            }
        }
    raise InvalidTransactionTransitionError(
        f"Checkout '{checkout.id}' was denied by policy; it cannot be authorized."
    )


def _guard_policy_pending_to_policy_denied(
    db: Session, transaction: Transaction, *, failure_reason: str | None, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    decision = policy_repository.get_decision_by_checkout(db, checkout.id)
    if decision is None or decision.decision != "deny":
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' was not denied by policy."
        )
    return {
        "failure_reason": failure_reason or decision.reason,
        "metadata": {"policy_decision_id": str(decision.id)},
    }


def _guard_authorized_to_payment_pending(
    db: Session, transaction: Transaction, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    payment = payment_repository.get_payment_by_checkout(db, checkout.id)
    if payment is None or payment.status != PAYMENT_STATUS_CREATED:
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' has no payment currently in progress."
        )
    return {
        "metadata": {"payment_id": str(payment.id), "provider_order_id": payment.provider_order_id}
    }


def _guard_payment_pending_to_payment_success(
    db: Session, transaction: Transaction, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    payment = payment_repository.get_payment_by_checkout(db, checkout.id)
    if payment is None or payment.status != PAYMENT_STATUS_SUCCESS:
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' does not have a successful payment."
        )
    return {
        "metadata": {
            "payment_id": str(payment.id),
            "provider_payment_id": payment.provider_payment_id,
        }
    }


def _guard_payment_pending_to_payment_failed(
    db: Session, transaction: Transaction, *, failure_reason: str | None, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    payment = payment_repository.get_payment_by_checkout(db, checkout.id)
    if payment is None or payment.status != PAYMENT_STATUS_FAILED:
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' does not have a failed payment."
        )
    return {
        "failure_reason": failure_reason or payment.failure_code,
        "metadata": {"payment_id": str(payment.id), "failure_code": payment.failure_code},
    }


def _guard_payment_failed_to_payment_pending(
    db: Session, transaction: Transaction, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    payment = payment_repository.get_payment_by_checkout(db, checkout.id)
    if payment is None or payment.status != PAYMENT_STATUS_CREATED:
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' does not have a new payment attempt in progress; "
            "initiate a retry before transitioning back to 'payment_pending'."
        )
    return {
        "failure_reason": None,
        "metadata": {"payment_id": str(payment.id), "provider_order_id": payment.provider_order_id},
    }


def _guard_payment_success_to_order_confirmed(
    db: Session, transaction: Transaction, **_: Any
) -> dict[str, Any]:
    checkout = _require_checkout(db, transaction)
    if checkout.status != "completed":
        raise InvalidTransactionTransitionError(
            f"Checkout '{checkout.id}' is not marked completed yet."
        )
    return {"metadata": {"checkout_id": str(checkout.id)}}


def _guard_to_cancelled(
    _db: Session, _transaction: Transaction, *, failure_reason: str | None, **__: Any
) -> dict[str, Any]:
    return {"failure_reason": failure_reason}


def _guard_to_failed(
    _db: Session, _transaction: Transaction, *, failure_reason: str | None, **__: Any
) -> dict[str, Any]:
    return {"failure_reason": failure_reason}


# The full, explicit state machine: every edge this transaction domain will
# accept, and the guard that must pass for it. Anything not a key here is
# rejected as `InvalidTransactionTransitionError` — including any attempt to
# leave a `TERMINAL_STATES` member.
_TRANSITIONS: dict[tuple[str, str], _Guard] = {
    (STATE_DISCOVERED, STATE_CART_CREATED): _guard_discovered_to_cart_created,
    (STATE_DISCOVERED, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_DISCOVERED, STATE_FAILED): _guard_to_failed,
    (STATE_CART_CREATED, STATE_CHECKOUT_CREATED): _guard_cart_created_to_checkout_created,
    (STATE_CART_CREATED, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_CART_CREATED, STATE_FAILED): _guard_to_failed,
    (STATE_CHECKOUT_CREATED, STATE_POLICY_PENDING): _guard_checkout_created_to_policy_pending,
    (STATE_CHECKOUT_CREATED, STATE_CHECKOUT_EXPIRED): _guard_any_to_checkout_expired,
    (STATE_CHECKOUT_CREATED, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_CHECKOUT_CREATED, STATE_FAILED): _guard_to_failed,
    (STATE_POLICY_PENDING, STATE_AUTHORIZED): _guard_policy_pending_to_authorized,
    (STATE_POLICY_PENDING, STATE_POLICY_DENIED): _guard_policy_pending_to_policy_denied,
    (STATE_POLICY_PENDING, STATE_CHECKOUT_EXPIRED): _guard_any_to_checkout_expired,
    (STATE_POLICY_PENDING, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_POLICY_PENDING, STATE_FAILED): _guard_to_failed,
    (STATE_AUTHORIZED, STATE_PAYMENT_PENDING): _guard_authorized_to_payment_pending,
    (STATE_AUTHORIZED, STATE_CHECKOUT_EXPIRED): _guard_any_to_checkout_expired,
    (STATE_AUTHORIZED, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_AUTHORIZED, STATE_FAILED): _guard_to_failed,
    (STATE_PAYMENT_PENDING, STATE_PAYMENT_SUCCESS): _guard_payment_pending_to_payment_success,
    (STATE_PAYMENT_PENDING, STATE_PAYMENT_FAILED): _guard_payment_pending_to_payment_failed,
    (STATE_PAYMENT_PENDING, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_PAYMENT_PENDING, STATE_FAILED): _guard_to_failed,
    (STATE_PAYMENT_FAILED, STATE_PAYMENT_PENDING): _guard_payment_failed_to_payment_pending,
    (STATE_PAYMENT_FAILED, STATE_CANCELLED): _guard_to_cancelled,
    (STATE_PAYMENT_FAILED, STATE_FAILED): _guard_to_failed,
    (STATE_PAYMENT_SUCCESS, STATE_ORDER_CONFIRMED): _guard_payment_success_to_order_confirmed,
}


def _validate_actor_type(actor_type: str) -> None:
    if actor_type not in (ACTOR_SYSTEM, ACTOR_AGENT):
        raise TransactionInputMismatchError(
            f"'{actor_type}' is not a known audit actor_type (expected '{ACTOR_SYSTEM}' or "
            f"'{ACTOR_AGENT}')."
        )


def create_transaction(
    db: Session,
    *,
    cart_id: uuid.UUID | None = None,
    checkout_id: uuid.UUID | None = None,
    actor_type: str = ACTOR_SYSTEM,
    actor_id: str | None = None,
    reason: str | None = None,
) -> Transaction:
    """Start a new transaction. Reflects the checkout flow "only where
    necessary" (item 6 of M6A): passing `checkout_id` for an already-created
    checkout starts the transaction directly at `checkout_created` — no
    change to `app.commerce.checkout` was needed for that, since a
    transaction only ever references a checkout, never the reverse. Passing
    neither starts at `discovered`, the pre-cart state.

    Creation is itself recorded as an audit event (`from_state=None`), added
    to the session in the same call that adds the `Transaction` row and
    flushed together — see the module docstring."""
    _validate_actor_type(actor_type)

    if checkout_id is not None:
        checkout = checkout_repository.get_checkout_by_id(db, checkout_id)
        if checkout is None:
            raise CheckoutNotFoundError(f"No checkout found with id '{checkout_id}'.")
        if cart_id is not None and cart_id != checkout.cart_id:
            raise TransactionInputMismatchError(
                f"Checkout '{checkout_id}' belongs to cart '{checkout.cart_id}', not the "
                f"supplied cart '{cart_id}'."
            )
        existing = repository.get_transaction_by_checkout(db, checkout_id)
        if existing is not None:
            raise CheckoutAlreadyHasTransactionError(
                f"Checkout '{checkout_id}' is already linked to transaction '{existing.id}'."
            )
        transaction = Transaction(
            cart_id=checkout.cart_id, checkout_id=checkout.id, state=STATE_CHECKOUT_CREATED
        )
    elif cart_id is not None:
        cart = cart_repository.get_cart_by_id(db, cart_id)
        if cart is None:
            raise CartNotFoundError(f"No cart found with id '{cart_id}'.")
        transaction = Transaction(cart_id=cart.id, state=STATE_CART_CREATED)
    else:
        transaction = Transaction(state=STATE_DISCOVERED)

    db.add(transaction)
    db.flush()  # assigns transaction.id, needed for the audit event's FK

    db.add(
        AuditEvent(
            transaction_id=transaction.id,
            from_state=None,
            to_state=transaction.state,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            event_metadata=None,
        )
    )
    db.flush()
    db.refresh(transaction)
    return transaction


def get_transaction(db: Session, transaction_id: uuid.UUID) -> Transaction:
    transaction = repository.get_transaction_by_id(db, transaction_id)
    if transaction is None:
        raise TransactionNotFoundError(f"No transaction found with id '{transaction_id}'.")
    return transaction


def list_audit_events(db: Session, transaction_id: uuid.UUID) -> list[AuditEvent]:
    """The transaction's full audit history, oldest first. Raises if the
    transaction itself doesn't exist, the same "not found" semantics every
    other `GET .../{transaction_id}/...` in this domain already has."""
    get_transaction(db, transaction_id)  # 404s before querying an empty/absent history
    return repository.list_audit_events_for_transaction(db, transaction_id)


def transition_transaction(
    db: Session,
    *,
    transaction_id: uuid.UUID,
    to_state: str,
    cart_id: uuid.UUID | None = None,
    checkout_id: uuid.UUID | None = None,
    failure_reason: str | None = None,
    actor_type: str = ACTOR_SYSTEM,
    actor_id: str | None = None,
    reason: str | None = None,
) -> Transaction:
    _validate_actor_type(actor_type)
    transaction = get_transaction(db, transaction_id)
    from_state = transaction.state

    guard = _TRANSITIONS.get((from_state, to_state))
    if guard is None:
        raise InvalidTransactionTransitionError(
            f"Transaction '{transaction_id}' cannot move from '{from_state}' to '{to_state}'."
        )

    # The guard runs — and can raise `InvalidTransactionTransitionError` or
    # `TransactionInputMismatchError` — entirely before anything below is
    # touched. A rejected transition therefore never reaches the point
    # where either the `Transaction` row or an `AuditEvent` is mutated/
    # added, so no misleading "successful transition" event is possible.
    updates = guard(
        db, transaction, cart_id=cart_id, checkout_id=checkout_id, failure_reason=failure_reason
    )
    event_metadata = updates.pop("metadata", None)
    # The guard's own derived reason (a policy denial reason, a payment
    # failure code, "checkout_expired") takes precedence over whatever the
    # caller passed as `reason` — it reflects a verified domain fact rather
    # than an unverified claim. Falls back to the caller's `reason` for
    # edges with nothing to derive (e.g. a plain cancellation, or a retry
    # that only clears `failure_reason` back to `None`).
    audit_reason = updates.get("failure_reason") or reason

    transaction.state = to_state
    for field, value in updates.items():
        setattr(transaction, field, value)

    db.add(
        AuditEvent(
            transaction_id=transaction.id,
            from_state=from_state,
            to_state=to_state,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=audit_reason,
            event_metadata=event_metadata,
        )
    )

    # One flush persists both the `Transaction` mutation and its `AuditEvent`
    # together: either both reach the database or (on a flush-time error,
    # e.g. a constraint violation) neither does — there is no window where
    # one exists without the other.
    db.flush()
    db.refresh(transaction)
    return transaction
