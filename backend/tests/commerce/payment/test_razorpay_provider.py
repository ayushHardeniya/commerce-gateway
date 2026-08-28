"""Unit tests for the Razorpay adapter's mapping/verification behavior.

None of these hit the network: `create_order` is exercised against a stub
standing in for `razorpay.Client().order`, and `verify_payment` is pure
local HMAC computation.
"""

import hashlib
import hmac

import pytest
import requests
from razorpay.errors import BadRequestError

from app.commerce.payment.provider import ProviderError, ProviderTimeoutError
from app.commerce.payment.razorpay import RazorpayConfigurationError, RazorpayProvider
from app.core.config import Settings


class _StubOrderResource:
    def __init__(self, *, response: dict | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def create(self, data: dict) -> dict:
        self.calls.append(data)
        if self._error is not None:
            raise self._error
        return self._response


def _provider() -> RazorpayProvider:
    return RazorpayProvider(key_id="rzp_test_abc123", key_secret="test_secret")


# --- verify_payment: pure HMAC, no network ---


def test_verify_payment_accepts_correctly_signed_payload() -> None:
    provider = _provider()
    message = b"order_ABC|pay_XYZ"
    signature = hmac.new(b"test_secret", message, hashlib.sha256).hexdigest()

    assert provider.verify_payment(
        provider_order_id="order_ABC", provider_payment_id="pay_XYZ", signature=signature
    )


def test_verify_payment_rejects_wrong_signature() -> None:
    provider = _provider()

    assert not provider.verify_payment(
        provider_order_id="order_ABC", provider_payment_id="pay_XYZ", signature="not-a-valid-sig"
    )


def test_verify_payment_rejects_signature_for_different_order() -> None:
    provider = _provider()
    message = b"order_OTHER|pay_XYZ"
    signature = hmac.new(b"test_secret", message, hashlib.sha256).hexdigest()

    assert not provider.verify_payment(
        provider_order_id="order_ABC", provider_payment_id="pay_XYZ", signature=signature
    )


def test_verify_payment_rejects_signature_signed_with_wrong_secret() -> None:
    provider = _provider()
    message = b"order_ABC|pay_XYZ"
    signature = hmac.new(b"someone_elses_secret", message, hashlib.sha256).hexdigest()

    assert not provider.verify_payment(
        provider_order_id="order_ABC", provider_payment_id="pay_XYZ", signature=signature
    )


# --- create_order: request/response mapping ---


def test_create_order_maps_response_fields() -> None:
    provider = _provider()
    provider._client.order = _StubOrderResource(
        response={"id": "order_fakeid123", "amount": 2000, "currency": "USD", "status": "created"}
    )

    order = provider.create_order(amount_minor_units=2000, currency="USD", receipt="checkout-1")

    assert order.provider_order_id == "order_fakeid123"
    assert order.amount_minor_units == 2000
    assert order.currency == "USD"
    assert provider._client.order.calls == [
        {"amount": 2000, "currency": "USD", "receipt": "checkout-1"}
    ]


def test_create_order_translates_provider_rejection() -> None:
    provider = _provider()
    provider._client.order = _StubOrderResource(error=BadRequestError("bad amount"))

    with pytest.raises(ProviderError):
        provider.create_order(amount_minor_units=-1, currency="USD", receipt="checkout-1")


def test_create_order_translates_timeout() -> None:
    provider = _provider()
    provider._client.order = _StubOrderResource(error=requests.exceptions.Timeout("slow"))

    with pytest.raises(ProviderTimeoutError):
        provider.create_order(amount_minor_units=2000, currency="USD", receipt="checkout-1")


def test_create_order_translates_connection_error() -> None:
    provider = _provider()
    provider._client.order = _StubOrderResource(
        error=requests.exceptions.ConnectionError("dns failure")
    )

    with pytest.raises(ProviderError):
        provider.create_order(amount_minor_units=2000, currency="USD", receipt="checkout-1")


# --- configuration ---


def test_from_settings_requires_both_credentials() -> None:
    settings = Settings(razorpay_key_id=None, razorpay_key_secret=None)

    with pytest.raises(RazorpayConfigurationError):
        RazorpayProvider.from_settings(settings)


def test_from_settings_builds_provider_with_key_id_exposed() -> None:
    settings = Settings(razorpay_key_id="rzp_test_abc123", razorpay_key_secret="s3cr3t")

    provider = RazorpayProvider.from_settings(settings)

    assert provider.key_id == "rzp_test_abc123"
