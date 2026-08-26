import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.commerce.cart.models import Cart
from app.commerce.checkout import service


def test_create_checkout(client: TestClient, cart_with_item: Cart) -> None:
    response = client.post("/api/checkouts", json={"cart_id": str(cart_with_item.id)})

    assert response.status_code == 201
    body = response.json()
    assert body["cart_id"] == str(cart_with_item.id)
    assert body["status"] == "active"
    assert body["total_minor_units"] == cart_with_item.subtotal_minor_units
    assert len(body["items"]) == 1


def test_create_checkout_for_empty_cart_returns_409(client: TestClient, cart: Cart) -> None:
    response = client.post("/api/checkouts", json={"cart_id": str(cart.id)})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "empty_cart"


def test_create_checkout_missing_cart_returns_404(client: TestClient) -> None:
    response = client.post("/api/checkouts", json={"cart_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "cart_not_found"


def test_create_checkout_unavailable_product_returns_409(
    client: TestClient, db_session: Session, cart_with_item: Cart, product: Product
) -> None:
    product.stock_quantity = 0
    db_session.flush()

    response = client.post("/api/checkouts", json={"cart_id": str(cart_with_item.id)})

    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == "product_unavailable"
    assert str(product.id) in body["product_ids"]


def test_create_checkout_price_changed_returns_409_with_structured_detail(
    client: TestClient, db_session: Session, cart_with_item: Cart, product: Product
) -> None:
    original_price = product.price_minor_units
    product.price_minor_units = original_price + 100
    db_session.flush()

    response = client.post("/api/checkouts", json={"cart_id": str(cart_with_item.id)})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "price_changed"
    change = detail["changes"][0]
    assert change["product_id"] == str(product.id)
    assert change["previous_unit_price_minor_units"] == original_price
    assert change["current_unit_price_minor_units"] == original_price + 100


def test_create_second_active_checkout_returns_409(
    client: TestClient, cart_with_item: Cart
) -> None:
    first = client.post("/api/checkouts", json={"cart_id": str(cart_with_item.id)})
    assert first.status_code == 201

    second = client.post("/api/checkouts", json={"cart_id": str(cart_with_item.id)})

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "invalid_cart_state"


def test_create_checkout_malformed_body_returns_422(client: TestClient) -> None:
    response = client.post("/api/checkouts", json={"cart_id": "not-a-uuid"})

    assert response.status_code == 422


# --- retrieval ---


def test_get_checkout(client: TestClient, cart_with_item: Cart) -> None:
    created = client.post("/api/checkouts", json={"cart_id": str(cart_with_item.id)})
    checkout_id = created.json()["id"]

    response = client.get(f"/api/checkouts/{checkout_id}")

    assert response.status_code == 200
    assert response.json()["id"] == checkout_id


def test_get_missing_checkout_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/checkouts/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "checkout_not_found"


def test_get_expired_checkout_reports_expired_status(
    client: TestClient, db_session: Session, cart_with_item: Cart
) -> None:
    checkout = service.create_checkout(db_session, cart_id=cart_with_item.id)
    checkout.created_at = datetime.now(UTC) - timedelta(hours=1)
    checkout.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    response = client.get(f"/api/checkouts/{checkout.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "expired"
