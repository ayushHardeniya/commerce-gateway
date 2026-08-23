import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product


@pytest.fixture
def merchant(db_session: Session) -> Merchant:
    obj = Merchant(name="Acme Co", slug="acme-co", description="A test merchant.")
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
