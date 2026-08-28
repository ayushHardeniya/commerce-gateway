"""Imports every ORM model so Base.metadata is complete for Alembic autogenerate."""

from app.catalog.models import Merchant, Product  # noqa: F401
from app.commerce.cart.models import Cart, CartItem  # noqa: F401
from app.commerce.checkout.models import Checkout, CheckoutItem  # noqa: F401
from app.commerce.payment.models import Payment  # noqa: F401
from app.commerce.policy.models import (  # noqa: F401
    CheckoutAuthorization,
    MerchantPolicy,
    PolicyDecision,
)
from app.commerce.transaction.models import Transaction  # noqa: F401
from app.db.session import Base

__all__ = ["Base"]
