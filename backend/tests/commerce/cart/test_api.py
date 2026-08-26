import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product
from app.commerce.cart.models import Cart

# --- create cart ---


def test_create_cart(client: TestClient, merchant: Merchant) -> None:
    response = client.post("/api/carts", json={"merchant_id": str(merchant.id)})

    assert response.status_code == 201
    body = response.json()
    assert body["merchant_id"] == str(merchant.id)
    assert body["items"] == []
    assert body["currency"] is None


def test_create_cart_missing_merchant_returns_404(client: TestClient) -> None:
    response = client.post("/api/carts", json={"merchant_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "merchant_not_found"


def test_create_cart_malformed_body_returns_422(client: TestClient) -> None:
    response = client.post("/api/carts", json={"merchant_id": "not-a-uuid"})

    assert response.status_code == 422


def test_create_cart_rejects_unknown_fields(client: TestClient, merchant: Merchant) -> None:
    response = client.post("/api/carts", json={"merchant_id": str(merchant.id), "extra": "nope"})

    assert response.status_code == 422


# --- retrieve cart ---


def test_get_cart(client: TestClient, cart: Cart) -> None:
    response = client.get(f"/api/carts/{cart.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(cart.id)


def test_get_missing_cart_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/carts/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "cart_not_found"


def test_get_cart_malformed_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/carts/not-a-uuid")

    assert response.status_code == 422


# --- add item ---


def test_add_item(client: TestClient, cart: Cart, product: Product) -> None:
    response = client.post(
        f"/api/carts/{cart.id}/items",
        json={"product_id": str(product.id), "quantity": 2},
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 2
    assert body["subtotal_minor_units"] == product.price_minor_units * 2


def test_add_item_missing_product_returns_404(client: TestClient, cart: Cart) -> None:
    response = client.post(
        f"/api/carts/{cart.id}/items", json={"product_id": str(uuid.uuid4()), "quantity": 1}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "product_not_found"


def test_add_item_unavailable_product_returns_409(
    client: TestClient, db_session: Session, cart: Cart, product: Product
) -> None:
    product.active = False
    db_session.flush()

    response = client.post(
        f"/api/carts/{cart.id}/items", json={"product_id": str(product.id), "quantity": 1}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "product_unavailable"


def test_add_item_invalid_quantity_returns_422(
    client: TestClient, cart: Cart, product: Product
) -> None:
    response = client.post(
        f"/api/carts/{cart.id}/items", json={"product_id": str(product.id), "quantity": 0}
    )

    assert response.status_code == 422


def test_add_item_missing_cart_returns_404(client: TestClient, product: Product) -> None:
    response = client.post(
        f"/api/carts/{uuid.uuid4()}/items", json={"product_id": str(product.id), "quantity": 1}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "cart_not_found"


# --- update item quantity ---


def test_update_item_quantity(client: TestClient, cart: Cart, product: Product) -> None:
    add_response = client.post(
        f"/api/carts/{cart.id}/items", json={"product_id": str(product.id), "quantity": 1}
    )
    item_id = add_response.json()["items"][0]["id"]

    response = client.patch(f"/api/carts/{cart.id}/items/{item_id}", json={"quantity": 5})

    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 5


def test_update_item_quantity_invalid_returns_422(
    client: TestClient, cart: Cart, product: Product
) -> None:
    add_response = client.post(
        f"/api/carts/{cart.id}/items", json={"product_id": str(product.id), "quantity": 1}
    )
    item_id = add_response.json()["items"][0]["id"]

    response = client.patch(f"/api/carts/{cart.id}/items/{item_id}", json={"quantity": -1})

    assert response.status_code == 422


def test_update_missing_item_returns_404(client: TestClient, cart: Cart) -> None:
    response = client.patch(f"/api/carts/{cart.id}/items/{uuid.uuid4()}", json={"quantity": 1})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "cart_item_not_found"


# --- remove item ---


def test_remove_item(client: TestClient, cart: Cart, product: Product) -> None:
    add_response = client.post(
        f"/api/carts/{cart.id}/items", json={"product_id": str(product.id), "quantity": 1}
    )
    item_id = add_response.json()["items"][0]["id"]

    response = client.delete(f"/api/carts/{cart.id}/items/{item_id}")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_remove_missing_item_returns_404(client: TestClient, cart: Cart) -> None:
    response = client.delete(f"/api/carts/{cart.id}/items/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "cart_item_not_found"
