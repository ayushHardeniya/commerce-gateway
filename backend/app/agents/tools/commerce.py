"""Cart and checkout tools available to the AI buyer.

Each tool is a thin wrapper over `app.commerce.cart.service` /
`app.commerce.checkout.service` — the same deterministic functions the HTTP
API calls. A tool never touches a repository or the database directly, and
it never computes a total or a price itself: totals, availability checks,
and price-snapshot revalidation all happen inside those services, so the
agent and the HTTP API can never disagree about what a cart or checkout
actually costs.

Gemini is given exactly these six capabilities — create/inspect a cart, add
or remove a line item, adjust a quantity, and create a checkout. It has no
tool for payment, authorization, or policy because none exists yet; that is
enforced by omission, not by a runtime check that could be misconfigured.
"""

import uuid
from typing import NoReturn

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.tools.base import Tool, ToolConflictError, ToolNotFoundError
from app.commerce.cart import service as cart_service
from app.commerce.cart.schemas import CartRead
from app.commerce.checkout import service as checkout_service
from app.commerce.checkout.schemas import CheckoutRead, to_checkout_read
from app.commerce.errors import CommerceError, is_not_found


def _raise_as_tool_error(exc: CommerceError) -> NoReturn:
    if is_not_found(exc):
        raise ToolNotFoundError(exc.message) from exc
    raise ToolConflictError(exc.message) from exc


class CreateCartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: uuid.UUID = Field(description="The merchant to shop from.")


class CreateCartTool(Tool[CreateCartInput, CartRead]):
    name = "create_cart"
    description = "Create a new, empty cart for one merchant."
    input_model = CreateCartInput
    output_model = CartRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: CreateCartInput) -> CartRead:
        try:
            cart = cart_service.create_cart(self._db, merchant_id=input.merchant_id)
        except CommerceError as exc:
            _raise_as_tool_error(exc)
        self._db.commit()
        return CartRead.model_validate(cart)


class GetCartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID


class GetCartTool(Tool[GetCartInput, CartRead]):
    name = "get_cart"
    description = "Retrieve a cart's current items and subtotal."
    input_model = GetCartInput
    output_model = CartRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: GetCartInput) -> CartRead:
        try:
            cart = cart_service.get_cart(self._db, input.cart_id)
        except CommerceError as exc:
            _raise_as_tool_error(exc)
        return CartRead.model_validate(cart)


class AddCartItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to add.")


class AddCartItemTool(Tool[AddCartItemInput, CartRead]):
    name = "add_cart_item"
    description = (
        "Add a product to a cart, or increase its quantity if it's already in the "
        "cart. Rejects unavailable products and quantities that aren't positive."
    )
    input_model = AddCartItemInput
    output_model = CartRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: AddCartItemInput) -> CartRead:
        try:
            cart = cart_service.add_item(
                self._db,
                cart_id=input.cart_id,
                product_id=input.product_id,
                quantity=input.quantity,
            )
        except CommerceError as exc:
            _raise_as_tool_error(exc)
        self._db.commit()
        return CartRead.model_validate(cart)


class UpdateCartItemQuantityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID
    item_id: uuid.UUID
    quantity: int = Field(gt=0, description="The new quantity for this line item.")


class UpdateCartItemQuantityTool(Tool[UpdateCartItemQuantityInput, CartRead]):
    name = "update_cart_item_quantity"
    description = "Change the quantity of an existing cart line item."
    input_model = UpdateCartItemQuantityInput
    output_model = CartRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: UpdateCartItemQuantityInput) -> CartRead:
        try:
            cart = cart_service.update_item_quantity(
                self._db, cart_id=input.cart_id, item_id=input.item_id, quantity=input.quantity
            )
        except CommerceError as exc:
            _raise_as_tool_error(exc)
        self._db.commit()
        return CartRead.model_validate(cart)


class RemoveCartItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID
    item_id: uuid.UUID


class RemoveCartItemTool(Tool[RemoveCartItemInput, CartRead]):
    name = "remove_cart_item"
    description = "Remove a line item from a cart entirely."
    input_model = RemoveCartItemInput
    output_model = CartRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: RemoveCartItemInput) -> CartRead:
        try:
            cart = cart_service.remove_item(self._db, cart_id=input.cart_id, item_id=input.item_id)
        except CommerceError as exc:
            _raise_as_tool_error(exc)
        self._db.commit()
        return CartRead.model_validate(cart)


class CreateCheckoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID


class CreateCheckoutTool(Tool[CreateCheckoutInput, CheckoutRead]):
    name = "create_checkout"
    description = (
        "Prepare a cart for purchase: revalidates that every product is still "
        "available and its price hasn't changed, then freezes a deterministic "
        "total. This only prepares a checkout — it never executes payment or "
        "authorization, which do not exist yet."
    )
    input_model = CreateCheckoutInput
    output_model = CheckoutRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: CreateCheckoutInput) -> CheckoutRead:
        try:
            checkout = checkout_service.create_checkout(self._db, cart_id=input.cart_id)
        except CommerceError as exc:
            _raise_as_tool_error(exc)
        self._db.commit()
        return to_checkout_read(checkout)
