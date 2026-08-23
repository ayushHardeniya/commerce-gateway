import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product


def _make_product(db_session: Session, merchant: Merchant, **overrides) -> Product:
    defaults = dict(
        merchant_id=merchant.id,
        sku=f"SKU-{uuid.uuid4().hex[:8]}",
        name="Product",
        description="A product.",
        price_minor_units=1500,
        currency="USD",
        stock_quantity=10,
    )
    defaults.update(overrides)
    product = Product(**defaults)
    db_session.add(product)
    db_session.flush()
    db_session.refresh(product)
    return product


# --- merchants ---


def test_list_merchants_returns_only_active_merchants(
    client: TestClient, db_session: Session
) -> None:
    active = Merchant(name="Active Co", slug="active-co", active=True)
    inactive = Merchant(name="Retired Co", slug="retired-co", active=False)
    db_session.add_all([active, inactive])
    db_session.flush()

    response = client.get("/api/catalog/merchants")

    assert response.status_code == 200
    slugs = {m["slug"] for m in response.json()}
    assert "active-co" in slugs
    assert "retired-co" not in slugs


def test_get_merchant_by_slug(client: TestClient, db_session: Session) -> None:
    db_session.add(Merchant(name="Acme Co", slug="acme-co", description="desc"))
    db_session.flush()

    response = client.get("/api/catalog/merchants/acme-co")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "acme-co"
    assert body["name"] == "Acme Co"
    assert set(body) == {
        "id",
        "name",
        "slug",
        "description",
        "active",
        "created_at",
        "updated_at",
    }


def test_get_merchant_not_found(client: TestClient) -> None:
    response = client.get("/api/catalog/merchants/does-not-exist")

    assert response.status_code == 404


# --- product listing / search ---


def test_list_products_for_merchant(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Blue Widget")
    _make_product(db_session, merchant, name="Red Widget")

    response = client.get(f"/api/catalog/merchants/{merchant.slug}/products")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    names = {item["name"] for item in body["items"]}
    assert names == {"Blue Widget", "Red Widget"}


def test_list_products_for_unknown_merchant_returns_404(client: TestClient) -> None:
    response = client.get("/api/catalog/merchants/does-not-exist/products")

    assert response.status_code == 404


def test_list_products_search_filters_by_name(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Wireless Mouse")
    _make_product(db_session, merchant, name="Wired Keyboard")

    response = client.get(
        f"/api/catalog/merchants/{merchant.slug}/products", params={"q": "wireless"}
    )

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Wireless Mouse"


def test_list_products_excludes_inactive_by_default(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Active Product", active=True)
    _make_product(db_session, merchant, name="Inactive Product", active=False)

    response = client.get(f"/api/catalog/merchants/{merchant.slug}/products")

    body = response.json()
    names = {item["name"] for item in body["items"]}
    assert names == {"Active Product"}


def test_list_products_include_inactive_flag(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Active Product", active=True)
    _make_product(db_session, merchant, name="Inactive Product", active=False)

    response = client.get(
        f"/api/catalog/merchants/{merchant.slug}/products", params={"include_inactive": True}
    )

    body = response.json()
    names = {item["name"] for item in body["items"]}
    assert names == {"Active Product", "Inactive Product"}


def test_list_products_in_stock_only_filter(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="In Stock", stock_quantity=5)
    _make_product(db_session, merchant, name="Out Of Stock", stock_quantity=0)

    response = client.get(
        f"/api/catalog/merchants/{merchant.slug}/products", params={"in_stock_only": True}
    )

    body = response.json()
    names = {item["name"] for item in body["items"]}
    assert names == {"In Stock"}


def test_list_products_pagination(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    for i in range(5):
        _make_product(db_session, merchant, name=f"Product {i}")

    response = client.get(
        f"/api/catalog/merchants/{merchant.slug}/products", params={"limit": 2, "offset": 2}
    )

    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert len(body["items"]) == 2


# --- global product search (merchant-agnostic discovery) ---


def test_global_search_returns_products_from_multiple_merchants(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    other_merchant = Merchant(name="Other Co", slug="other-co")
    db_session.add(other_merchant)
    db_session.flush()

    _make_product(db_session, merchant, name="Widget A")
    _make_product(db_session, other_merchant, name="Widget B")

    response = client.get("/api/catalog/products")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    slugs = {item["merchant"]["slug"] for item in body["items"]}
    assert slugs == {merchant.slug, other_merchant.slug}


def test_global_search_filters_by_query(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    other_merchant = Merchant(name="Other Co", slug="other-co")
    db_session.add(other_merchant)
    db_session.flush()

    _make_product(db_session, merchant, name="Wireless Mouse")
    _make_product(db_session, other_merchant, name="Wired Keyboard")

    response = client.get("/api/catalog/products", params={"q": "wireless"})

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Wireless Mouse"


def test_global_search_excludes_inactive_by_default(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Active Product", active=True)
    _make_product(db_session, merchant, name="Inactive Product", active=False)

    response = client.get("/api/catalog/products")

    names = {item["name"] for item in response.json()["items"]}
    assert names == {"Active Product"}


def test_global_search_include_inactive_flag(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Active Product", active=True)
    _make_product(db_session, merchant, name="Inactive Product", active=False)

    response = client.get("/api/catalog/products", params={"include_inactive": True})

    names = {item["name"] for item in response.json()["items"]}
    assert names == {"Active Product", "Inactive Product"}


def test_global_search_in_stock_only_filter(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="In Stock", stock_quantity=5)
    _make_product(db_session, merchant, name="Out Of Stock", stock_quantity=0)

    response = client.get("/api/catalog/products", params={"in_stock_only": True})

    names = {item["name"] for item in response.json()["items"]}
    assert names == {"In Stock"}


def test_global_search_pagination(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    for i in range(5):
        _make_product(db_session, merchant, name=f"Product {i}")

    response = client.get("/api/catalog/products", params={"limit": 2, "offset": 2})

    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert len(body["items"]) == 2


# --- single product retrieval / agent-readable view ---


def test_get_product_returns_agent_readable_view(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    product = _make_product(
        db_session,
        merchant,
        name="Wireless Headphones",
        description="Noise-cancelling over-ear headphones.",
        price_minor_units=4999,
        currency="USD",
        stock_quantity=25,
    )

    response = client.get(f"/api/catalog/products/{product.id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "sku",
        "name",
        "description",
        "price_minor_units",
        "currency",
        "active",
        "stock_quantity",
        "merchant",
        "created_at",
        "updated_at",
        "is_available",
    }
    assert body["price_minor_units"] == 4999
    assert isinstance(body["price_minor_units"], int)
    assert body["currency"] == "USD"
    assert body["is_available"] is True
    assert body["merchant"] == {
        "id": str(merchant.id),
        "name": merchant.name,
        "slug": merchant.slug,
        "active": True,
    }


def test_out_of_stock_product_is_not_available(
    client: TestClient, db_session: Session, merchant: Merchant
) -> None:
    product = _make_product(db_session, merchant, stock_quantity=0)

    response = client.get(f"/api/catalog/products/{product.id}")

    assert response.json()["is_available"] is False


def test_inactive_merchant_makes_product_unavailable(
    client: TestClient, db_session: Session
) -> None:
    inactive_merchant = Merchant(name="Closed Shop", slug="closed-shop", active=False)
    db_session.add(inactive_merchant)
    db_session.flush()
    product = _make_product(db_session, inactive_merchant, active=True, stock_quantity=10)

    response = client.get(f"/api/catalog/products/{product.id}")

    body = response.json()
    assert body["active"] is True
    assert body["merchant"]["active"] is False
    assert body["is_available"] is False


def test_get_product_not_found(client: TestClient) -> None:
    response = client.get(f"/api/catalog/products/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_product_invalid_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/catalog/products/not-a-uuid")

    assert response.status_code == 422
