"""Policy evaluation and authorization business rules.

This is the deterministic boundary described in
`docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`: an LLM
may ask `evaluate_checkout` "what does policy say about this checkout", but
nothing here ever consults an LLM, and the amount/currency evaluated always
comes from the authoritative, already-frozen `Checkout` row — never a value
a caller supplies.

`evaluate_checkout` is idempotent: a checkout gets exactly one
`PolicyDecision`, computed once and returned unchanged on every later call,
so a merchant editing their policy afterward can never retroactively change
what an already-made decision meant.
"""

import uuid

from sqlalchemy.orm import Session

from app.catalog import repository as catalog_repository
from app.commerce.cart import repository as cart_repository
from app.commerce.checkout import repository as checkout_repository
from app.commerce.checkout.models import Checkout
from app.commerce.errors import (
    AlreadyAuthorizedError,
    AuthorizationDeniedError,
    AuthorizationInvalidError,
    AuthorizationNotRequiredError,
    CheckoutExpiredError,
    CheckoutInvalidError,
    CheckoutNotFoundError,
    MerchantNotFoundError,
    PolicyDecisionNotFoundError,
)
from app.commerce.policy import repository as policy_repository
from app.commerce.policy.models import CheckoutAuthorization, MerchantPolicy, PolicyDecision

# The safe default applied when a merchant has never configured an explicit
# policy: no autonomous spending at all — every non-zero checkout requires
# human authorization until the merchant raises this limit themselves. See
# docs/decisions/0006-policy-snapshot-and-explicit-authorization.md.
DEFAULT_AUTONOMOUS_LIMIT_MINOR_UNITS = 0
# Reserved `PolicyDecision.policy_version` value meaning "the default above
# was applied, no explicit MerchantPolicy existed yet" — never a version a
# real MerchantPolicy row can have (`version` starts at 1 and only grows).
DEFAULT_POLICY_VERSION = 0

DECISION_ALLOW = "allow"
DECISION_REQUIRE_AUTHORIZATION = "require_authorization"
DECISION_DENY = "deny"

REASON_WITHIN_LIMIT = "within_autonomous_limit"
REASON_LIMIT_EXCEEDED = "autonomous_limit_exceeded"
REASON_CHECKOUT_EXPIRED = "checkout_expired"
REASON_CHECKOUT_INVALID = "checkout_invalid"
REASON_CURRENCY_MISMATCH = "currency_mismatch"


def get_policy(db: Session, merchant_id: uuid.UUID) -> MerchantPolicy | None:
    """The explicitly configured policy for a merchant, or `None` if they
    have never set one. Distinct from `evaluate_checkout`, which falls back
    to `DEFAULT_AUTONOMOUS_LIMIT_MINOR_UNITS` internally rather than ever
    treating "no policy" as unrestricted autonomous spending."""
    merchant = catalog_repository.get_merchant_by_id(db, merchant_id)
    if merchant is None:
        raise MerchantNotFoundError(f"No merchant found with id '{merchant_id}'.")
    return policy_repository.get_policy_by_merchant(db, merchant_id)


def upsert_policy(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    autonomous_limit_minor_units: int,
    currency: str,
) -> MerchantPolicy:
    """Create the merchant's policy, or update it in place and bump
    `version` if one already exists. There is exactly one active policy row
    per merchant — see the ADR for why a full version-history table isn't
    needed to keep past decisions meaningful."""
    merchant = catalog_repository.get_merchant_by_id(db, merchant_id)
    if merchant is None:
        raise MerchantNotFoundError(f"No merchant found with id '{merchant_id}'.")

    policy = policy_repository.get_policy_by_merchant(db, merchant_id)
    if policy is None:
        policy = MerchantPolicy(
            merchant_id=merchant_id,
            version=1,
            autonomous_limit_minor_units=autonomous_limit_minor_units,
            currency=currency.upper(),
        )
        db.add(policy)
    else:
        policy.version += 1
        policy.autonomous_limit_minor_units = autonomous_limit_minor_units
        policy.currency = currency.upper()

    db.flush()
    db.refresh(policy)
    return policy


def evaluate_checkout(db: Session, checkout_id: uuid.UUID) -> PolicyDecision:
    checkout = checkout_repository.get_checkout_by_id(db, checkout_id)
    if checkout is None:
        raise CheckoutNotFoundError(f"No checkout found with id '{checkout_id}'.")

    existing = policy_repository.get_decision_by_checkout(db, checkout_id)
    if existing is not None:
        return existing

    merchant_id = _merchant_id_for_checkout(db, checkout)
    policy = policy_repository.get_policy_by_merchant(db, merchant_id)

    if policy is not None:
        policy_id = policy.id
        policy_version = policy.version
        limit = policy.autonomous_limit_minor_units
        policy_currency = policy.currency
    else:
        policy_id = None
        policy_version = DEFAULT_POLICY_VERSION
        limit = DEFAULT_AUTONOMOUS_LIMIT_MINOR_UNITS
        policy_currency = checkout.currency

    decision, reason = _decide(checkout, limit=limit, policy_currency=policy_currency)

    record = PolicyDecision(
        checkout_id=checkout.id,
        merchant_id=merchant_id,
        policy_id=policy_id,
        policy_version=policy_version,
        autonomous_limit_minor_units=limit,
        policy_currency=policy_currency,
        decision=decision,
        reason=reason,
        amount_minor_units=checkout.total_minor_units,
        currency=checkout.currency,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    return record


def get_decision(db: Session, checkout_id: uuid.UUID) -> PolicyDecision:
    decision = policy_repository.get_decision_by_checkout(db, checkout_id)
    if decision is None:
        raise PolicyDecisionNotFoundError(
            f"Checkout '{checkout_id}' has not been evaluated against policy yet."
        )
    return decision


def get_authorization(db: Session, checkout_id: uuid.UUID) -> CheckoutAuthorization | None:
    return policy_repository.get_authorization_by_checkout(db, checkout_id)


def authorize_checkout(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    amount_minor_units: int,
    currency: str,
) -> CheckoutAuthorization:
    """Explicit, one-time human approval of a REQUIRE_AUTHORIZATION decision.

    The caller must state the amount/currency they are approving; it is
    checked against both the checkout's *current* authoritative total and
    the decision's own snapshot before anything is recorded — see the
    invariants in `docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`.
    Nothing about this function is reachable from the agent tool layer.
    """
    checkout = checkout_repository.get_checkout_by_id(db, checkout_id)
    if checkout is None:
        raise CheckoutNotFoundError(f"No checkout found with id '{checkout_id}'.")

    decision = policy_repository.get_decision_by_checkout(db, checkout_id)
    if decision is None:
        raise PolicyDecisionNotFoundError(
            f"Checkout '{checkout_id}' has not been evaluated against policy yet."
        )

    if policy_repository.get_authorization_by_checkout(db, checkout_id) is not None:
        raise AlreadyAuthorizedError(f"Checkout '{checkout_id}' has already been authorized.")

    if decision.decision == DECISION_DENY:
        raise AuthorizationDeniedError(
            f"Checkout '{checkout_id}' was denied by policy and cannot be authorized."
        )
    if decision.decision == DECISION_ALLOW:
        raise AuthorizationNotRequiredError(
            f"Checkout '{checkout_id}' was already allowed by policy; nothing to authorize."
        )

    effective_status = checkout.effective_status
    if effective_status == "expired":
        raise CheckoutExpiredError(f"Checkout '{checkout_id}' has expired.")
    if effective_status != "active":
        raise CheckoutInvalidError(f"Checkout '{checkout_id}' is '{effective_status}', not active.")

    current_matches_request = (
        checkout.total_minor_units == amount_minor_units and checkout.currency == currency
    )
    current_matches_decision = (
        checkout.total_minor_units == decision.amount_minor_units
        and checkout.currency == decision.currency
    )
    if not (current_matches_request and current_matches_decision):
        raise AuthorizationInvalidError(
            f"Checkout '{checkout_id}' no longer matches the policy decision being authorized "
            "(amount or currency changed)."
        )

    authorization = CheckoutAuthorization(
        checkout_id=checkout.id,
        policy_decision_id=decision.id,
        amount_minor_units=amount_minor_units,
        currency=currency,
    )
    db.add(authorization)
    db.flush()
    db.refresh(authorization)
    return authorization


def _merchant_id_for_checkout(db: Session, checkout: Checkout) -> uuid.UUID:
    cart = cart_repository.get_cart_by_id(db, checkout.cart_id)
    assert cart is not None, "Checkout.cart_id is ON DELETE RESTRICT; the cart must still exist."
    return cart.merchant_id


def _decide(checkout: Checkout, *, limit: int, policy_currency: str) -> tuple[str, str]:
    effective_status = checkout.effective_status
    if effective_status == "expired":
        return DECISION_DENY, REASON_CHECKOUT_EXPIRED
    if effective_status != "active":
        return DECISION_DENY, REASON_CHECKOUT_INVALID
    if checkout.currency != policy_currency:
        return DECISION_DENY, REASON_CURRENCY_MISMATCH
    if checkout.total_minor_units <= limit:
        return DECISION_ALLOW, REASON_WITHIN_LIMIT
    return DECISION_REQUIRE_AUTHORIZATION, REASON_LIMIT_EXCEEDED
