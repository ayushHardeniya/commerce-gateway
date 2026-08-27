"""Request/response schemas for the policy/authorization API and agent tools."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.commerce.policy.models import CheckoutAuthorization, PolicyDecision


class PolicyDecisionValue(StrEnum):
    ALLOW = "allow"
    REQUIRE_AUTHORIZATION = "require_authorization"
    DENY = "deny"


class MerchantPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    version: int = Field(gt=0)
    autonomous_limit_minor_units: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    created_at: datetime
    updated_at: datetime


class UpsertMerchantPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autonomous_limit_minor_units: int = Field(
        ge=0, description="The largest checkout total this merchant allows without authorization."
    )
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 currency code.")


class PolicyDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    checkout_id: uuid.UUID
    decision: PolicyDecisionValue
    reason: str
    amount_minor_units: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    policy_version: int = Field(
        ge=0, description="0 means the safe default was applied; no explicit policy existed."
    )
    autonomous_limit_minor_units: int = Field(
        ge=0, description="The limit that was actually compared against, snapshotted."
    )
    created_at: datetime
    authorized: bool = Field(description="Whether a human has since authorized this checkout.")
    authorized_at: datetime | None = None


def to_policy_decision_read(
    decision: PolicyDecision, authorization: CheckoutAuthorization | None
) -> PolicyDecisionRead:
    return PolicyDecisionRead(
        id=decision.id,
        checkout_id=decision.checkout_id,
        decision=PolicyDecisionValue(decision.decision),
        reason=decision.reason,
        amount_minor_units=decision.amount_minor_units,
        currency=decision.currency,
        policy_version=decision.policy_version,
        autonomous_limit_minor_units=decision.autonomous_limit_minor_units,
        created_at=decision.created_at,
        authorized=authorization is not None,
        authorized_at=authorization.created_at if authorization else None,
    )


class AuthorizeCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor_units: int = Field(
        ge=0, description="The checkout total being approved; must match it exactly."
    )
    currency: str = Field(
        min_length=3, max_length=3, description="The checkout currency being approved."
    )


class CheckoutAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    checkout_id: uuid.UUID
    policy_decision_id: uuid.UUID
    amount_minor_units: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    created_at: datetime
