"""The only module that imports the Razorpay SDK.

Implements `PaymentProvider` (`app.commerce.payment.provider`) against
Razorpay's Orders API (order creation) and their documented payment
signature scheme (verification):
https://razorpay.com/docs/payments/server-integration/python/integration-steps/

Signature verification is done locally with the account secret rather than
via `client.utility.verify_payment_signature`, but implements the exact same
documented algorithm: `HMAC-SHA256("{order_id}|{payment_id}", key_secret)`
must equal the signature Checkout returned. Doing this with the stdlib
directly (rather than through the SDK's own helper) keeps the one security-
critical check in this module fully unit-testable with zero network access
and no dependency on the SDK's internal exception types.

Nothing outside this module knows Razorpay exists.
"""

from __future__ import annotations

import hashlib
import hmac

import razorpay
import requests
from razorpay.errors import BadRequestError, GatewayError, ServerError

from app.commerce.payment.provider import (
    PaymentProvider,
    ProviderError,
    ProviderOrder,
    ProviderTimeoutError,
)
from app.core.config import Settings

_PROVIDER_REJECTED = (BadRequestError, GatewayError, ServerError)


class RazorpayConfigurationError(ProviderError):
    """Raised when Razorpay can't be used because it isn't configured."""


class RazorpayProvider:
    """`PaymentProvider` backed by Razorpay Test Mode."""

    def __init__(self, *, key_id: str, key_secret: str) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._client = razorpay.Client(auth=(key_id, key_secret))

    @classmethod
    def from_settings(cls, settings: Settings) -> RazorpayProvider:
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise RazorpayConfigurationError(
                "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are not configured; payment is unavailable."
            )
        return cls(key_id=settings.razorpay_key_id, key_secret=settings.razorpay_key_secret)

    @property
    def key_id(self) -> str:
        """The public key id the frontend Checkout widget needs. Never the
        secret — see `app.commerce.payment.router`, the only other place
        this is read."""
        return self._key_id

    def create_order(
        self, *, amount_minor_units: int, currency: str, receipt: str
    ) -> ProviderOrder:
        try:
            order = self._client.order.create(
                {"amount": amount_minor_units, "currency": currency, "receipt": receipt}
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderTimeoutError(f"Razorpay order creation timed out: {exc}") from exc
        except _PROVIDER_REJECTED as exc:
            raise ProviderError(f"Razorpay rejected the order request: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderError(f"Razorpay order creation failed: {exc}") from exc

        return ProviderOrder(
            provider_order_id=order["id"],
            amount_minor_units=order["amount"],
            currency=order["currency"],
        )

    def verify_payment(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        message = f"{provider_order_id}|{provider_payment_id}".encode()
        expected = hmac.new(self._key_secret.encode(), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


# Structural check: `RazorpayProvider` must satisfy `PaymentProvider` without
# inheriting from it (Protocol is duck-typed by design).
_: type[PaymentProvider] = RazorpayProvider
