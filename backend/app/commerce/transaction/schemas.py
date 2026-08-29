"""Request/response schemas for the transaction and audit-event APIs."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AuditActorType(StrEnum):
    """Who a transition (or a transaction's creation) is being recorded on
    behalf of — deterministic application/system code, or a request that
    identified itself as acting for the AI buyer. Not an authentication
    system: a caller simply states which it is, the same trust level the
    rest of this internal API already operates at."""

    SYSTEM = "system"
    AGENT = "agent"


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
    actor_type: AuditActorType = AuditActorType.SYSTEM
    actor_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class TransitionTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_state: TransactionState
    cart_id: uuid.UUID | None = None
    checkout_id: uuid.UUID | None = None
    failure_reason: str | None = Field(default=None, max_length=500)
    actor_type: AuditActorType = AuditActorType.SYSTEM
    actor_id: str | None = Field(default=None, max_length=200)
    # A caller-supplied explanation for the audit trail. Only used when the
    # transition's guard has no domain-derived reason of its own (e.g. a
    # plain cancellation) — see
    # `app.commerce.transaction.service.transition_transaction`.
    reason: str | None = Field(default=None, max_length=500)


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cart_id: uuid.UUID | None
    checkout_id: uuid.UUID | None
    state: TransactionState
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    transaction_id: uuid.UUID
    from_state: TransactionState | None
    to_state: TransactionState
    actor_type: AuditActorType
    actor_id: str | None
    reason: str | None
    event_metadata: dict | None
    created_at: datetime
