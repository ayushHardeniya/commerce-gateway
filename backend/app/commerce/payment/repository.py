"""Read/write access to the payments table. No business rules here — see
`app.commerce.payment.service`."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce.payment.models import Payment


def get_payment_by_checkout(db: Session, checkout_id: uuid.UUID) -> Payment | None:
    stmt = select(Payment).where(Payment.checkout_id == checkout_id)
    return db.scalars(stmt).first()
