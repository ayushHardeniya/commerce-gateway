import uuid

from sqlalchemy.orm import Session

from app.agents.tools.base import ToolErrorCode
from app.agents.tools.catalog import GetProductTool, SearchCatalogTool
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
    obj = Product(**defaults)
    db_session.add(obj)
    db_session.flush()
    db_session.refresh(obj)
    return obj


# --- search_catalog ---


def test_search_catalog_returns_matching_products(db_session: Session, merchant: Merchant) -> None:
    _make_product(db_session, merchant, name="Blue Widget")
    _make_product(db_session, merchant, name="Red Widget")

    result = SearchCatalogTool(db_session).run({})

    assert result.ok
    assert result.output.total == 2
    assert {item.name for item in result.output.items} == {"Blue Widget", "Red Widget"}


def test_search_catalog_filters_by_query(db_session: Session, merchant: Merchant) -> None:
    _make_product(db_session, merchant, name="Wireless Mouse")
    _make_product(db_session, merchant, name="Wired Keyboard")

    result = SearchCatalogTool(db_session).run({"query": "wireless"})

    assert result.ok
    assert result.output.total == 1
    assert result.output.items[0].name == "Wireless Mouse"


def test_search_catalog_pagination(db_session: Session, merchant: Merchant) -> None:
    for i in range(5):
        _make_product(db_session, merchant, name=f"Product {i}")

    result = SearchCatalogTool(db_session).run({"limit": 2, "offset": 2})

    assert result.ok
    assert result.output.total == 5
    assert result.output.limit == 2
    assert result.output.offset == 2
    assert len(result.output.items) == 2


def test_search_catalog_spans_multiple_merchants(db_session: Session, merchant: Merchant) -> None:
    other_merchant = Merchant(name="Other Co", slug="other-co")
    db_session.add(other_merchant)
    db_session.flush()
    _make_product(db_session, merchant, name="Widget A")
    _make_product(db_session, other_merchant, name="Widget B")

    result = SearchCatalogTool(db_session).run({})

    assert result.ok
    slugs = {item.merchant.slug for item in result.output.items}
    assert slugs == {merchant.slug, other_merchant.slug}


def test_search_catalog_in_stock_only_filter(db_session: Session, merchant: Merchant) -> None:
    _make_product(db_session, merchant, name="In Stock", stock_quantity=5)
    _make_product(db_session, merchant, name="Out Of Stock", stock_quantity=0)

    result = SearchCatalogTool(db_session).run({"in_stock_only": True})

    assert result.ok
    assert {item.name for item in result.output.items} == {"In Stock"}


def test_search_catalog_excludes_inactive_by_default(
    db_session: Session, merchant: Merchant
) -> None:
    _make_product(db_session, merchant, name="Active Product", active=True)
    _make_product(db_session, merchant, name="Inactive Product", active=False)

    result = SearchCatalogTool(db_session).run({})

    assert result.ok
    assert {item.name for item in result.output.items} == {"Active Product"}


def test_search_catalog_include_inactive_flag(db_session: Session, merchant: Merchant) -> None:
    _make_product(db_session, merchant, name="Active Product", active=True)
    _make_product(db_session, merchant, name="Inactive Product", active=False)

    result = SearchCatalogTool(db_session).run({"include_inactive": True})

    assert result.ok
    assert {item.name for item in result.output.items} == {"Active Product", "Inactive Product"}


def test_search_catalog_no_matches_is_not_an_error(db_session: Session, merchant: Merchant) -> None:
    _make_product(db_session, merchant, name="Widget")

    result = SearchCatalogTool(db_session).run({"query": "nonexistent"})

    assert result.ok
    assert result.output.items == []
    assert result.output.total == 0


def test_search_catalog_invalid_limit_returns_structured_error(
    db_session: Session, merchant: Merchant
) -> None:
    result = SearchCatalogTool(db_session).run({"limit": 0})

    assert not result.ok
    assert result.output is None
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_search_catalog_invalid_offset_returns_structured_error(
    db_session: Session, merchant: Merchant
) -> None:
    result = SearchCatalogTool(db_session).run({"offset": -1})

    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_search_catalog_unknown_field_returns_structured_error(
    db_session: Session, merchant: Merchant
) -> None:
    result = SearchCatalogTool(db_session).run({"limit": "not-a-number"})

    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_search_catalog_is_deterministic(db_session: Session, merchant: Merchant) -> None:
    _make_product(db_session, merchant, name="Widget")

    tool = SearchCatalogTool(db_session)
    first = tool.run({"query": "widget"})
    second = tool.run({"query": "widget"})

    assert first.ok and second.ok
    assert first.output == second.output


# --- get_product ---


def test_get_product_returns_agent_readable_view(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    result = GetProductTool(db_session).run({"product_id": str(product.id)})

    assert result.ok
    assert result.output.id == product.id
    assert result.output.name == product.name
    assert result.output.merchant.slug == merchant.slug
    assert result.output.is_available is True


def test_get_product_missing_returns_not_found_error(db_session: Session) -> None:
    result = GetProductTool(db_session).run({"product_id": str(uuid.uuid4())})

    assert not result.ok
    assert result.output is None
    assert result.error.code == ToolErrorCode.NOT_FOUND


def test_get_product_malformed_id_returns_invalid_input_error(db_session: Session) -> None:
    result = GetProductTool(db_session).run({"product_id": "not-a-uuid"})

    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_get_product_missing_field_returns_invalid_input_error(db_session: Session) -> None:
    result = GetProductTool(db_session).run({})

    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_get_product_is_deterministic(db_session: Session, product: Product) -> None:
    tool = GetProductTool(db_session)
    first = tool.run({"product_id": str(product.id)})
    second = tool.run({"product_id": str(product.id)})

    assert first.ok and second.ok
    assert first.output == second.output
