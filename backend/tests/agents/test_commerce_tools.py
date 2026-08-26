import uuid

from sqlalchemy.orm import Session

from app.agents.tools.base import ToolErrorCode
from app.agents.tools.commerce import (
    AddCartItemTool,
    CreateCartTool,
    CreateCheckoutTool,
    GetCartTool,
    RemoveCartItemTool,
    UpdateCartItemQuantityTool,
)
from app.catalog.models import Merchant, Product

# --- create_cart ---


def test_create_cart_tool(db_session: Session, merchant: Merchant) -> None:
    result = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)})

    assert result.ok
    assert result.output.merchant_id == merchant.id
    assert result.output.items == []


def test_create_cart_tool_missing_merchant_is_not_found(db_session: Session) -> None:
    result = CreateCartTool(db_session).run({"merchant_id": str(uuid.uuid4())})

    assert not result.ok
    assert result.error.code == ToolErrorCode.NOT_FOUND


def test_create_cart_tool_malformed_input_is_invalid(db_session: Session) -> None:
    result = CreateCartTool(db_session).run({"merchant_id": "not-a-uuid"})

    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_create_cart_tool_rejects_unknown_fields(db_session: Session, merchant: Merchant) -> None:
    result = CreateCartTool(db_session).run({"merchant_id": str(merchant.id), "discount": "100%"})

    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


# --- add_cart_item / get_cart ---


def test_add_cart_item_tool(db_session: Session, merchant: Merchant, product: Product) -> None:
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id

    result = AddCartItemTool(db_session).run(
        {"cart_id": str(cart_id), "product_id": str(product.id), "quantity": 3}
    )

    assert result.ok
    assert len(result.output.items) == 1
    assert result.output.items[0].quantity == 3
    assert result.output.subtotal_minor_units == product.price_minor_units * 3


def test_add_cart_item_tool_unavailable_product_is_conflict(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    product.stock_quantity = 0
    db_session.flush()
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id

    result = AddCartItemTool(db_session).run(
        {"cart_id": str(cart_id), "product_id": str(product.id), "quantity": 1}
    )

    assert not result.ok
    assert result.error.code == ToolErrorCode.CONFLICT


def test_add_cart_item_tool_invalid_quantity_is_conflict(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id

    result = AddCartItemTool(db_session).run(
        {"cart_id": str(cart_id), "product_id": str(product.id), "quantity": 0}
    )

    # Rejected by the tool's own schema (quantity must be > 0) before the
    # service layer is ever reached.
    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_add_cart_item_tool_missing_cart_is_not_found(
    db_session: Session, product: Product
) -> None:
    result = AddCartItemTool(db_session).run(
        {"cart_id": str(uuid.uuid4()), "product_id": str(product.id), "quantity": 1}
    )

    assert not result.ok
    assert result.error.code == ToolErrorCode.NOT_FOUND


def test_get_cart_tool_inspects_current_contents(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id
    AddCartItemTool(db_session).run(
        {"cart_id": str(cart_id), "product_id": str(product.id), "quantity": 2}
    )

    result = GetCartTool(db_session).run({"cart_id": str(cart_id)})

    assert result.ok
    assert len(result.output.items) == 1
    assert result.output.items[0].product.name == product.name


def test_get_cart_tool_missing_cart_is_not_found(db_session: Session) -> None:
    result = GetCartTool(db_session).run({"cart_id": str(uuid.uuid4())})

    assert not result.ok
    assert result.error.code == ToolErrorCode.NOT_FOUND


# --- update / remove ---


def test_update_cart_item_quantity_tool(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    cart = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output
    add_result = AddCartItemTool(db_session).run(
        {"cart_id": str(cart.id), "product_id": str(product.id), "quantity": 1}
    )
    item_id = add_result.output.items[0].id

    result = UpdateCartItemQuantityTool(db_session).run(
        {"cart_id": str(cart.id), "item_id": str(item_id), "quantity": 9}
    )

    assert result.ok
    assert result.output.items[0].quantity == 9


def test_remove_cart_item_tool(db_session: Session, merchant: Merchant, product: Product) -> None:
    cart = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output
    add_result = AddCartItemTool(db_session).run(
        {"cart_id": str(cart.id), "product_id": str(product.id), "quantity": 1}
    )
    item_id = add_result.output.items[0].id

    result = RemoveCartItemTool(db_session).run({"cart_id": str(cart.id), "item_id": str(item_id)})

    assert result.ok
    assert result.output.items == []


def test_remove_cart_item_tool_missing_item_is_not_found(
    db_session: Session, merchant: Merchant
) -> None:
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id

    result = RemoveCartItemTool(db_session).run(
        {"cart_id": str(cart_id), "item_id": str(uuid.uuid4())}
    )

    assert not result.ok
    assert result.error.code == ToolErrorCode.NOT_FOUND


# --- create_checkout ---


def test_create_checkout_tool(db_session: Session, merchant: Merchant, product: Product) -> None:
    cart = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output
    AddCartItemTool(db_session).run(
        {"cart_id": str(cart.id), "product_id": str(product.id), "quantity": 2}
    )

    result = CreateCheckoutTool(db_session).run({"cart_id": str(cart.id)})

    assert result.ok
    assert result.output.status == "active"
    assert result.output.total_minor_units == product.price_minor_units * 2


def test_create_checkout_tool_empty_cart_is_conflict(
    db_session: Session, merchant: Merchant
) -> None:
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id

    result = CreateCheckoutTool(db_session).run({"cart_id": str(cart_id)})

    assert not result.ok
    assert result.error.code == ToolErrorCode.CONFLICT


def test_create_checkout_tool_price_changed_is_conflict(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    cart = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output
    AddCartItemTool(db_session).run(
        {"cart_id": str(cart.id), "product_id": str(product.id), "quantity": 1}
    )
    product.price_minor_units += 1
    db_session.flush()

    result = CreateCheckoutTool(db_session).run({"cart_id": str(cart.id)})

    assert not result.ok
    assert result.error.code == ToolErrorCode.CONFLICT


def test_create_checkout_tool_missing_cart_is_not_found(db_session: Session) -> None:
    result = CreateCheckoutTool(db_session).run({"cart_id": str(uuid.uuid4())})

    assert not result.ok
    assert result.error.code == ToolErrorCode.NOT_FOUND
