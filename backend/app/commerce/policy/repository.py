"""Read/write access to the policy and authorization tables. No business
rules here — see `app.commerce.policy.service`."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce.policy.models import CheckoutAuthorization, MerchantPolicy, PolicyDecision


def get_policy_by_merchant(db: Session, merchant_id: uuid.UUID) -> MerchantPolicy | None:
    stmt = select(MerchantPolicy).where(MerchantPolicy.merchant_id == merchant_id)
    return db.scalars(stmt).first()


def get_decision_by_checkout(db: Session, checkout_id: uuid.UUID) -> PolicyDecision | None:
    stmt = select(PolicyDecision).where(PolicyDecision.checkout_id == checkout_id)
    return db.scalars(stmt).first()


def get_authorization_by_checkout(
    db: Session, checkout_id: uuid.UUID
) -> CheckoutAuthorization | None:
    stmt = select(CheckoutAuthorization).where(CheckoutAuthorization.checkout_id == checkout_id)
    return db.scalars(stmt).first()
