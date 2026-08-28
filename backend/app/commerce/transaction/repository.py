"""Read/write access to the transactions table. No business rules here —
see `app.commerce.transaction.service`."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce.transaction.models import Transaction


def get_transaction_by_id(db: Session, transaction_id: uuid.UUID) -> Transaction | None:
    stmt = select(Transaction).where(Transaction.id == transaction_id)
    return db.scalars(stmt).first()


def get_transaction_by_checkout(db: Session, checkout_id: uuid.UUID) -> Transaction | None:
    stmt = select(Transaction).where(Transaction.checkout_id == checkout_id)
    return db.scalars(stmt).first()
