"""Request/response schemas for the payment API.

There is deliberately no request body for initiating payment: the amount
and currency charged are never something a caller may supply — see
`app.commerce.payment.service.initiate_payment`, which always reads them
from the checkout's own frozen total.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.commerce.payment.models import Payment


class PaymentStatus(StrEnum):
    CREATED = "created"
    SUCCESS = "success"
    FAILED = "failed"


class PaymentOrderRead(BaseModel):
    """What the frontend needs to open Razorpay Checkout — nothing more.
    `razorpay_key_id` is the public key id; safe to expose to the frontend,
    unlike the key secret, which is never returned by any API response."""

    payment_id: uuid.UUID
    checkout_id: uuid.UUID
    provider: str
    provider_order_id: str
    amount_minor_units: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    razorpay_key_id: str


def to_payment_order_read(payment: Payment, *, razorpay_key_id: str) -> PaymentOrderRead:
    return PaymentOrderRead(
        payment_id=payment.id,
        checkout_id=payment.checkout_id,
        provider=payment.provider,
        provider_order_id=payment.provider_order_id,
        amount_minor_units=payment.amount_minor_units,
        currency=payment.currency,
        razorpay_key_id=razorpay_key_id,
    )


class ConfirmPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    checkout_id: uuid.UUID
    provider: str
    provider_order_id: str
    provider_payment_id: str | None
    status: PaymentStatus
    amount_minor_units: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime
