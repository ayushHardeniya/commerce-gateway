import pytest
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.commerce.cart import service as cart_service
from app.commerce.cart.models import Cart


@pytest.fixture
def cart_with_item(db_session: Session, cart: Cart, product: Product) -> Cart:
    return cart_service.add_item(db_session, cart_id=cart.id, product_id=product.id, quantity=2)
