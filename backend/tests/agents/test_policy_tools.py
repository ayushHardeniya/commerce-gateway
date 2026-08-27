import uuid

from sqlalchemy.orm import Session

from app.agents.tools import DEFAULT_TOOLS, POLICY_TOOLS
from app.agents.tools.base import ToolErrorCode
from app.agents.tools.commerce import AddCartItemTool, CreateCartTool, CreateCheckoutTool
from app.agents.tools.policy import EvaluateCheckoutPolicyTool
from app.catalog.models import Merchant, Product
from app.commerce.policy import service as policy_service


def _create_checkout(db_session: Session, merchant: Merchant, product: Product) -> uuid.UUID:
    cart_id = CreateCartTool(db_session).run({"merchant_id": str(merchant.id)}).output.id
    AddCartItemTool(db_session).run(
        {"cart_id": str(cart_id), "product_id": str(product.id), "quantity": 2}
    )
    checkout = CreateCheckoutTool(db_session).run({"cart_id": str(cart_id)}).output
    return checkout.id


def test_evaluate_checkout_policy_tool_returns_decision(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    checkout_id = _create_checkout(db_session, merchant, product)

    result = EvaluateCheckoutPolicyTool(db_session).run({"checkout_id": str(checkout_id)})

    assert result.ok
    assert result.output.decision == "require_authorization"
    assert result.output.reason == "autonomous_limit_exceeded"
    assert result.output.authorized is False


def test_evaluate_checkout_policy_tool_reflects_allow(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=999_999, currency="USD"
    )
    checkout_id = _create_checkout(db_session, merchant, product)

    result = EvaluateCheckoutPolicyTool(db_session).run({"checkout_id": str(checkout_id)})

    assert result.ok
    assert result.output.decision == "allow"


def test_evaluate_checkout_policy_tool_is_idempotent(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    checkout_id = _create_checkout(db_session, merchant, product)

    first = EvaluateCheckoutPolicyTool(db_session).run({"checkout_id": str(checkout_id)})
    second = EvaluateCheckoutPolicyTool(db_session).run({"checkout_id": str(checkout_id)})

    assert first.output.id == second.output.id


def test_evaluate_checkout_policy_tool_missing_checkout_is_not_found(db_session: Session) -> None:
    result = EvaluateCheckoutPolicyTool(db_session).run({"checkout_id": str(uuid.uuid4())})

    assert not result.ok
    assert result.error.code == ToolErrorCode.NOT_FOUND


def test_evaluate_checkout_policy_tool_rejects_unknown_fields(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    checkout_id = _create_checkout(db_session, merchant, product)

    result = EvaluateCheckoutPolicyTool(db_session).run(
        {"checkout_id": str(checkout_id), "amount_minor_units": 100}
    )

    # An agent cannot smuggle its own amount into the evaluation — the input
    # schema rejects anything beyond `checkout_id` outright.
    assert not result.ok
    assert result.error.code == ToolErrorCode.INVALID_INPUT


def test_no_authorization_capability_is_exposed_to_the_agent() -> None:
    """The AI buyer must have no path to granting, overriding, or
    manufacturing a human authorization — enforced by omission from the
    declared tool set, not a runtime permission check."""
    assert POLICY_TOOLS == (EvaluateCheckoutPolicyTool,)

    forbidden_fragments = ("authoriz", "approve", "grant", "bypass", "override")
    for tool_cls in DEFAULT_TOOLS:
        lowered = tool_cls.name.lower()
        if tool_cls is EvaluateCheckoutPolicyTool:
            continue
        assert not any(fragment in lowered for fragment in forbidden_fragments), tool_cls.name


def test_catalog_and_commerce_tools_still_present() -> None:
    tool_names = {tool_cls.name for tool_cls in DEFAULT_TOOLS}
    assert {
        "search_catalog",
        "get_product",
        "create_cart",
        "get_cart",
        "add_cart_item",
        "update_cart_item_quantity",
        "remove_cart_item",
        "create_checkout",
        "evaluate_checkout_policy",
    } <= tool_names
