"""HTTP API for checkout, under `/api/checkouts`.

Thin, like `app.commerce.cart.router`: business rules live in
`app.commerce.checkout.service`, errors map through
`app.commerce.errors.raise_http_error`.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.commerce.checkout import service
from app.commerce.checkout.schemas import CheckoutRead, CreateCheckoutRequest, to_checkout_read
from app.commerce.errors import CommerceError, raise_http_error
from app.db.session import get_db

router = APIRouter(prefix="/api/checkouts", tags=["checkout"])


@router.post("", response_model=CheckoutRead, status_code=status.HTTP_201_CREATED)
def create_checkout(request: CreateCheckoutRequest, db: Session = Depends(get_db)) -> CheckoutRead:
    try:
        checkout = service.create_checkout(db, cart_id=request.cart_id)
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return to_checkout_read(checkout)


@router.get("/{checkout_id}", response_model=CheckoutRead)
def get_checkout(checkout_id: uuid.UUID, db: Session = Depends(get_db)) -> CheckoutRead:
    try:
        checkout = service.get_checkout(db, checkout_id)
    except CommerceError as exc:
        raise_http_error(exc)
    return to_checkout_read(checkout)
