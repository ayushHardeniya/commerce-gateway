"""Request/response schemas for the merchant catalog API.

`ProductCatalogView` is the agent-readable catalog representation: it embeds
enough merchant identity, pricing, and availability information that a
consumer never needs a second lookup just to decide whether a product is a
valid candidate to buy.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MerchantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


class MerchantSummary(BaseModel):
    """Minimal merchant identity, embedded in a product's catalog view."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    active: bool


class ProductCatalogView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    price_minor_units: int = Field(
        ge=0, description="Price as an integer count of the currency's minor units."
    )
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 currency code.")
    active: bool
    stock_quantity: int = Field(ge=0)
    merchant: MerchantSummary
    created_at: datetime
    updated_at: datetime
    is_available: bool = Field(
        description="Sourced directly from Product.is_available — the single "
        "definition of the availability rule. Not re-derived here."
    )


class ProductPage(BaseModel):
    """A page of catalog products, with the total match count for pagination."""

    items: list[ProductCatalogView]
    total: int
    limit: int
    offset: int
