"""Provider-neutral payment execution interface.

`app.commerce.payment.service` depends only on this `PaymentProvider`
protocol — never on a concrete provider — so Razorpay-specific types and API
details stay confined to `app.commerce.payment.razorpay`. A future second
provider gets its own adapter implementing the same protocol; nothing else
in the payment domain would change.

Deliberately just the two operations M5 actually needs. No refund/capture/
subscription/webhook methods — those aren't part of this milestone (see
`ARCHITECTURE.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """A payment provider request failed (rejected, network error, bad
    response). Never raised for an eligibility/authorization failure — that
    is always an `app.commerce.errors.CommerceError`, decided by our own
    deterministic code before the provider is ever called."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond in time."""


@dataclass(frozen=True)
class ProviderOrder:
    provider_order_id: str
    amount_minor_units: int
    currency: str


class PaymentProvider(Protocol):
    def create_order(
        self, *, amount_minor_units: int, currency: str, receipt: str
    ) -> ProviderOrder:
        """Create a payable order for exactly this amount/currency."""
        ...

    def verify_payment(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        """Whether `signature` proves `provider_payment_id` was actually
        paid against `provider_order_id`. A pure cryptographic check — never
        a network call, so it can never itself move money."""
        ...
