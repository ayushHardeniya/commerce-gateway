from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.commerce.cart import service as cart_service
from app.commerce.cart.models import Cart
from app.commerce.checkout import service as checkout_service
from app.commerce.checkout.models import Checkout
from app.commerce.payment.provider import ProviderError, ProviderOrder, ProviderTimeoutError
from app.commerce.payment.router import get_payment_provider
from app.main import app


@pytest.fixture
def cart_with_item(db_session: Session, cart: Cart, product: Product) -> Cart:
    return cart_service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=2)


@pytest.fixture
def checkout(db_session: Session, cart_with_item: Cart) -> Checkout:
    return checkout_service.create_checkout(db_session, cart_id=cart_with_item.id)


class FakePaymentProvider:
    """A deterministic, in-memory `PaymentProvider` — never touches the
    network, never depends on live Razorpay credentials. `create_order`
    outcomes are driven by a queue so a test can script exactly one
    success/failure/timeout without any mocking framework; `verify_payment`
    is driven by a single flag a test can flip."""

    key_id = "rzp_test_fake_key_id"

    def __init__(self) -> None:
        self.create_order_outcomes: list[str] = []
        self.next_signature_valid = True
        self.created_orders: list[ProviderOrder] = []
        self.verify_calls: list[dict[str, str]] = []
        self._order_counter = 0

    def queue_create_order_failure(self) -> None:
        self.create_order_outcomes.append("failure")

    def queue_create_order_timeout(self) -> None:
        self.create_order_outcomes.append("timeout")

    def create_order(
        self, *, amount_minor_units: int, currency: str, receipt: str
    ) -> ProviderOrder:
        outcome = self.create_order_outcomes.pop(0) if self.create_order_outcomes else "success"
        if outcome == "failure":
            raise ProviderError("simulated provider failure")
        if outcome == "timeout":
            raise ProviderTimeoutError("simulated provider timeout")

        self._order_counter += 1
        order = ProviderOrder(
            provider_order_id=f"order_fake_{self._order_counter}",
            amount_minor_units=amount_minor_units,
            currency=currency,
        )
        self.created_orders.append(order)
        return order

    def verify_payment(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        self.verify_calls.append(
            {
                "provider_order_id": provider_order_id,
                "provider_payment_id": provider_payment_id,
                "signature": signature,
            }
        )
        return self.next_signature_valid


@pytest.fixture
def fake_provider() -> FakePaymentProvider:
    return FakePaymentProvider()


@pytest.fixture
def client(client: TestClient, fake_provider: FakePaymentProvider) -> Iterator[TestClient]:
    """The root `client` fixture, with `get_payment_provider` additionally
    overridden to the deterministic fake — so payment API tests never need
    live Razorpay credentials."""
    app.dependency_overrides[get_payment_provider] = lambda: fake_provider
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
