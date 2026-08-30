from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.commerce.cart import service as cart_service
from app.commerce.cart.models import Cart
from app.commerce.checkout import service as checkout_service
from app.commerce.checkout.models import Checkout
from app.commerce.payment.router import get_payment_provider
from app.main import app
from tests.commerce.payment.conftest import FakePaymentProvider


@pytest.fixture
def cart_with_item(db_session: Session, cart: Cart, product: Product) -> Cart:
    return cart_service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=2)


@pytest.fixture
def checkout(db_session: Session, cart_with_item: Cart) -> Checkout:
    return checkout_service.create_checkout(db_session, cart_id=cart_with_item.id)


@pytest.fixture
def fake_provider() -> FakePaymentProvider:
    return FakePaymentProvider()


@pytest.fixture
def client(client: TestClient, fake_provider: FakePaymentProvider) -> Iterator[TestClient]:
    """The root `client` fixture, with `get_payment_provider` additionally
    overridden to the same deterministic fake `tests/commerce/payment/conftest.py`
    already defines — M8A's full-lifecycle tests drive payment through the
    real HTTP endpoints, so they need this override too, but reuse the
    existing fake rather than a new one."""
    app.dependency_overrides[get_payment_provider] = lambda: fake_provider
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
