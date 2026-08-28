"""HTTP API for payment, under `/api/checkouts/{checkout_id}/payment`.

Thin, like the checkout/policy routers: business rules live in
`app.commerce.payment.service`, errors map through
`app.commerce.errors.raise_http_error`. `get_payment_provider` is the one
place a concrete `RazorpayProvider` gets constructed — routes otherwise only
ever pass it around as the provider-neutral `PaymentProvider` the service
depends on.

No route here accepts an authoritative amount or currency from the caller —
`initiate_payment` takes no request body at all, and `confirm_payment`'s
body carries only Razorpay's own returned identifiers/signature.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.commerce.errors import CommerceError, raise_http_error
from app.commerce.payment import service
from app.commerce.payment.razorpay import RazorpayConfigurationError, RazorpayProvider
from app.commerce.payment.schemas import (
    ConfirmPaymentRequest,
    PaymentOrderRead,
    PaymentRead,
    to_payment_order_read,
)
from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/api/checkouts", tags=["payment"])


def get_payment_provider() -> RazorpayProvider:
    try:
        return RazorpayProvider.from_settings(get_settings())
    except RazorpayConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/{checkout_id}/payment",
    response_model=PaymentOrderRead,
    status_code=status.HTTP_201_CREATED,
)
def initiate_payment(
    checkout_id: uuid.UUID,
    db: Session = Depends(get_db),
    provider: RazorpayProvider = Depends(get_payment_provider),
) -> PaymentOrderRead:
    try:
        payment = service.initiate_payment(db, checkout_id=checkout_id, provider=provider)
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return to_payment_order_read(payment, razorpay_key_id=provider.key_id)


@router.post("/{checkout_id}/payment/confirm", response_model=PaymentRead)
def confirm_payment(
    checkout_id: uuid.UUID,
    request: ConfirmPaymentRequest,
    db: Session = Depends(get_db),
    provider: RazorpayProvider = Depends(get_payment_provider),
) -> PaymentRead:
    try:
        payment = service.confirm_payment(
            db,
            checkout_id=checkout_id,
            provider_order_id=request.razorpay_order_id,
            provider_payment_id=request.razorpay_payment_id,
            signature=request.razorpay_signature,
            provider=provider,
        )
    except CommerceError as exc:
        # `confirm_payment` may have already flushed a durable `failed`
        # state (invalid signature, eligibility lost) before raising — that
        # write must survive this request even though it ends in an error.
        # A commit with nothing pending (the not-found/invalid-state raises,
        # which write nothing) is a harmless no-op.
        db.commit()
        raise_http_error(exc)
    db.commit()
    return PaymentRead.model_validate(payment)


@router.get("/{checkout_id}/payment", response_model=PaymentRead)
def get_payment(checkout_id: uuid.UUID, db: Session = Depends(get_db)) -> PaymentRead:
    try:
        payment = service.get_payment(db, checkout_id)
    except CommerceError as exc:
        raise_http_error(exc)
    return PaymentRead.model_validate(payment)
