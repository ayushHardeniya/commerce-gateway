"""Request/response schemas for the transaction API."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TransactionState(StrEnum):
    DISCOVERED = "discovered"
    CART_CREATED = "cart_created"
    CHECKOUT_CREATED = "checkout_created"
    POLICY_PENDING = "policy_pending"
    AUTHORIZED = "authorized"
    PAYMENT_PENDING = "payment_pending"
    PAYMENT_SUCCESS = "payment_success"
    ORDER_CONFIRMED = "order_confirmed"
    POLICY_DENIED = "policy_denied"
    PAYMENT_FAILED = "payment_failed"
    CHECKOUT_EXPIRED = "checkout_expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CreateTransactionRequest(BaseModel):
    """Both fields are optional and mutually informative, never both
    required: supplying `checkout_id` starts the transaction directly at
    `checkout_created` (the checkout flow integration point — see
    `app.commerce.transaction.service.create_transaction`); supplying only
    `cart_id` starts it at `cart_created`; supplying neither starts it at
    `discovered`."""

    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID | None = None
    checkout_id: uuid.UUID | None = None


class TransitionTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_state: TransactionState
    cart_id: uuid.UUID | None = None
    checkout_id: uuid.UUID | None = None
    failure_reason: str | None = Field(default=None, max_length=500)


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cart_id: uuid.UUID | None
    checkout_id: uuid.UUID | None
    state: TransactionState
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
