"""HTTP API for merchant policy, policy decisions, and authorization, under
`/api/policy`.

Thin, like the cart/checkout routers: business rules live in
`app.commerce.policy.service`, errors map through
`app.commerce.errors.raise_http_error` — the same structured error framework
cart/checkout already use, not a second one.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.commerce.errors import (
    AuthorizationRequiredError,
    CommerceError,
    PolicyNotFoundError,
    raise_http_error,
)
from app.commerce.policy import service
from app.commerce.policy.schemas import (
    AuthorizeCheckoutRequest,
    CheckoutAuthorizationRead,
    MerchantPolicyRead,
    PolicyDecisionRead,
    UpsertMerchantPolicyRequest,
    to_policy_decision_read,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/policy", tags=["policy"])


@router.get("/merchants/{merchant_id}", response_model=MerchantPolicyRead)
def get_merchant_policy(
    merchant_id: uuid.UUID, db: Session = Depends(get_db)
) -> MerchantPolicyRead:
    try:
        policy = service.get_policy(db, merchant_id)
    except CommerceError as exc:
        raise_http_error(exc)
    if policy is None:
        raise_http_error(
            PolicyNotFoundError(f"No policy has been configured for merchant '{merchant_id}'.")
        )
    return MerchantPolicyRead.model_validate(policy)


@router.put("/merchants/{merchant_id}", response_model=MerchantPolicyRead)
def upsert_merchant_policy(
    merchant_id: uuid.UUID, request: UpsertMerchantPolicyRequest, db: Session = Depends(get_db)
) -> MerchantPolicyRead:
    try:
        policy = service.upsert_policy(
            db,
            merchant_id=merchant_id,
            autonomous_limit_minor_units=request.autonomous_limit_minor_units,
            currency=request.currency,
        )
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return MerchantPolicyRead.model_validate(policy)


@router.post(
    "/checkouts/{checkout_id}/evaluate",
    response_model=PolicyDecisionRead,
    status_code=status.HTTP_200_OK,
)
def evaluate_checkout(checkout_id: uuid.UUID, db: Session = Depends(get_db)) -> PolicyDecisionRead:
    try:
        decision = service.evaluate_checkout(db, checkout_id)
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    authorization = service.get_authorization(db, checkout_id)
    return to_policy_decision_read(decision, authorization)


@router.get("/checkouts/{checkout_id}/decision", response_model=PolicyDecisionRead)
def get_policy_decision(
    checkout_id: uuid.UUID, db: Session = Depends(get_db)
) -> PolicyDecisionRead:
    try:
        decision = service.get_decision(db, checkout_id)
    except CommerceError as exc:
        raise_http_error(exc)
    authorization = service.get_authorization(db, checkout_id)
    return to_policy_decision_read(decision, authorization)


@router.post(
    "/checkouts/{checkout_id}/authorize",
    response_model=CheckoutAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_checkout(
    checkout_id: uuid.UUID, request: AuthorizeCheckoutRequest, db: Session = Depends(get_db)
) -> CheckoutAuthorizationRead:
    try:
        authorization = service.authorize_checkout(
            db,
            checkout_id=checkout_id,
            amount_minor_units=request.amount_minor_units,
            currency=request.currency,
        )
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return CheckoutAuthorizationRead.model_validate(authorization)


@router.get("/checkouts/{checkout_id}/authorization", response_model=CheckoutAuthorizationRead)
def get_authorization(
    checkout_id: uuid.UUID, db: Session = Depends(get_db)
) -> CheckoutAuthorizationRead:
    try:
        service.get_decision(db, checkout_id)
    except CommerceError as exc:
        raise_http_error(exc)
    authorization = service.get_authorization(db, checkout_id)
    if authorization is None:
        raise_http_error(
            AuthorizationRequiredError(f"Checkout '{checkout_id}' has not been authorized yet.")
        )
    return CheckoutAuthorizationRead.model_validate(authorization)
