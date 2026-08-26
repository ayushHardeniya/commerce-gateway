"""Request/response schemas for the checkout API and agent tools.

`CheckoutRead.status` is sourced from `Checkout.effective_status` (which
folds in expiry), not the raw stored `status` column — see
`to_checkout_read`, the one place that distinction is made explicit.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.commerce.checkout.models import Checkout


class CheckoutStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CreateCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID


class CheckoutItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID | None
    product_name: str
    product_sku: str
    quantity: int = Field(gt=0)
    unit_price_minor_units: int = Field(ge=0)
    subtotal_minor_units: int = Field(ge=0)


class CheckoutRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cart_id: uuid.UUID
    status: CheckoutStatus
    total_minor_units: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    items: list[CheckoutItemRead]
    created_at: datetime
    expires_at: datetime


def to_checkout_read(checkout: Checkout) -> CheckoutRead:
    """`CheckoutRead.model_validate(checkout)` would read the raw, stored
    `status` column — this reads `effective_status` instead, so an expired
    checkout is reported as expired without anything having to write that
    transition to the database first."""
    return CheckoutRead(
        id=checkout.id,
        cart_id=checkout.cart_id,
        status=CheckoutStatus(checkout.effective_status),
        total_minor_units=checkout.total_minor_units,
        currency=checkout.currency,
        items=[CheckoutItemRead.model_validate(item) for item in checkout.items],
        created_at=checkout.created_at,
        expires_at=checkout.expires_at,
    )
