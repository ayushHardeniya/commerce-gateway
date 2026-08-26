"""Request/response schemas for the cart API and agent tools.

`CartRead` embeds the full `ProductCatalogView` for each line item's
product, the same agent-readable representation the catalog API returns —
so a consumer never needs a second lookup to see what's actually in a cart.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.schemas import ProductCatalogView


class CreateCartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: uuid.UUID


class AddCartItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: int = Field(gt=0)


class UpdateCartItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(gt=0)


class CartItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    product: ProductCatalogView
    quantity: int = Field(gt=0)
    unit_price_minor_units: int = Field(
        ge=0, description="Price captured when this item was added — not necessarily current."
    )
    subtotal_minor_units: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class CartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    currency: str | None = Field(
        default=None, min_length=3, max_length=3, description="Null while the cart is empty."
    )
    items: list[CartItemRead]
    subtotal_minor_units: int = Field(
        ge=0, description="Deterministic sum(unit_price_minor_units × quantity) over all items."
    )
    created_at: datetime
    updated_at: datetime
