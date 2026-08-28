"""HTTP API for the transaction state machine, under `/api/transactions`.

Thin, like the checkout/policy/payment routers: business rules and every
guarded transition live in `app.commerce.transaction.service`, errors map
through `app.commerce.errors.raise_http_error`. There is no route (and no
agent `Tool`) that lets a caller set `state` directly on create or bypass
`transition_transaction`'s guards — every state change goes through the one
validated state machine.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.commerce.errors import CommerceError, raise_http_error
from app.commerce.transaction import service
from app.commerce.transaction.schemas import (
    CreateTransactionRequest,
    TransactionRead,
    TransitionTransactionRequest,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/transactions", tags=["transaction"])


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    request: CreateTransactionRequest, db: Session = Depends(get_db)
) -> TransactionRead:
    try:
        transaction = service.create_transaction(
            db, cart_id=request.cart_id, checkout_id=request.checkout_id
        )
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return TransactionRead.model_validate(transaction)


@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(transaction_id: uuid.UUID, db: Session = Depends(get_db)) -> TransactionRead:
    try:
        transaction = service.get_transaction(db, transaction_id)
    except CommerceError as exc:
        raise_http_error(exc)
    return TransactionRead.model_validate(transaction)


@router.post("/{transaction_id}/transitions", response_model=TransactionRead)
def transition_transaction(
    transaction_id: uuid.UUID,
    request: TransitionTransactionRequest,
    db: Session = Depends(get_db),
) -> TransactionRead:
    try:
        transaction = service.transition_transaction(
            db,
            transaction_id=transaction_id,
            to_state=request.to_state.value,
            cart_id=request.cart_id,
            checkout_id=request.checkout_id,
            failure_reason=request.failure_reason,
        )
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return TransactionRead.model_validate(transaction)
