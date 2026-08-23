"""Catalog discovery tools available to the AI buyer.

Both tools are thin deterministic wrappers over `app.catalog.repository` —
the same functions `app/catalog/router.py` calls for the HTTP API — so the
agent and the HTTP API can never drift into different filtering/availability
semantics. Neither tool makes an HTTP request back into our own API, and
neither does any ranking, semantic search, or LLM call of its own.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.tools.base import Tool, ToolNotFoundError
from app.catalog import repository
from app.catalog.schemas import ProductCatalogView, ProductPage


class SearchCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None, description="Case-insensitive substring match on product name."
    )
    in_stock_only: bool = Field(default=False, description="Only include in-stock products.")
    include_inactive: bool = Field(
        default=False,
        description="Include inactive products. An AI buyer should normally leave this false.",
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchCatalogTool(Tool[SearchCatalogInput, ProductPage]):
    name = "search_catalog"
    description = (
        "Search the product catalog across all merchants by name text, stock, and "
        "active status, with pagination. Deterministic filtering only — no semantic "
        "search or ranking. Returns a page of agent-readable product views plus the "
        "total match count."
    )
    input_model = SearchCatalogInput
    output_model = ProductPage

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: SearchCatalogInput) -> ProductPage:
        items, total = repository.search_products(
            self._db,
            query=input.query,
            active_only=not input.include_inactive,
            in_stock_only=input.in_stock_only,
            limit=input.limit,
            offset=input.offset,
        )
        return ProductPage(
            items=[ProductCatalogView.model_validate(item) for item in items],
            total=total,
            limit=input.limit,
            offset=input.offset,
        )


class GetProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID


class GetProductTool(Tool[GetProductInput, ProductCatalogView]):
    name = "get_product"
    description = "Retrieve a single product by ID as the agent-readable catalog view."
    input_model = GetProductInput
    output_model = ProductCatalogView

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: GetProductInput) -> ProductCatalogView:
        product = repository.get_product_by_id(self._db, input.product_id)
        if product is None:
            raise ToolNotFoundError(f"No product found with id '{input.product_id}'.")
        return ProductCatalogView.model_validate(product)
