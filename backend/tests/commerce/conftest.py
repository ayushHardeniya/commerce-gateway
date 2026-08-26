import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product
from app.commerce.cart import service as cart_service
from app.commerce.cart.models import Cart


@pytest.fixture
def merchant(db_session: Session) -> Merchant:
    obj = Merchant(name="Acme Co", slug="acme-co", description="A test merchant.")
    db_session.add(obj)
    db_session.flush()
    return obj


@pytest.fixture
def other_merchant(db_session: Session) -> Merchant:
    obj = Merchant(name="Other Co", slug="other-co")
    db_session.add(obj)
    db_session.flush()
    return obj


@pytest.fixture
def product(db_session: Session, merchant: Merchant) -> Product:
    obj = Product(
        merchant_id=merchant.id,
        sku="ACME-001",
        name="Widget",
        description="A perfectly ordinary widget.",
        price_minor_units=1000,
        currency="USD",
        stock_quantity=10,
    )
    db_session.add(obj)
    db_session.flush()
    db_session.refresh(obj)
    return obj


@pytest.fixture
def second_product(db_session: Session, merchant: Merchant) -> Product:
    obj = Product(
        merchant_id=merchant.id,
        sku="ACME-002",
        name="Gadget",
        price_minor_units=2500,
        currency="USD",
        stock_quantity=5,
    )
    db_session.add(obj)
    db_session.flush()
    db_session.refresh(obj)
    return obj


@pytest.fixture
def cart(db_session: Session, merchant: Merchant) -> Cart:
    return cart_service.create_cart(db_session, merchant_id=merchant.id)
