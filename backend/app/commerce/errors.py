"""Structured domain errors shared by the cart and checkout routers.

Mirrors the {code, message} shape already used by the agent tool contract
(`app.agents.tools.base.ToolError`) rather than inventing a second error
vocabulary: every `CommerceError` carries a short machine-readable `code`
and a human-readable `message`. `raise_http_error` is the one place that
turns one into a FastAPI `HTTPException` with a structured `detail`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException


class CommerceError(Exception):
    code: str

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message}


class CartNotFoundError(CommerceError):
    code = "cart_not_found"


class MerchantNotFoundError(CommerceError):
    code = "merchant_not_found"


class ProductNotFoundError(CommerceError):
    code = "product_not_found"


class CartItemNotFoundError(CommerceError):
    code = "cart_item_not_found"


class CheckoutNotFoundError(CommerceError):
    code = "checkout_not_found"


class InvalidQuantityError(CommerceError):
    code = "invalid_quantity"


class EmptyCartError(CommerceError):
    code = "empty_cart"


class MerchantMismatchError(CommerceError):
    """The product belongs to a different merchant than the cart."""

    code = "merchant_mismatch"


class CurrencyMismatchError(CommerceError):
    """The product's currency doesn't match the currency already committed
    to by earlier items in this cart."""

    code = "currency_mismatch"


class InvalidCartStateError(CommerceError):
    code = "invalid_cart_state"


class CheckoutExpiredError(CommerceError):
    code = "checkout_expired"


class ProductUnavailableError(CommerceError):
    code = "product_unavailable"

    def __init__(self, message: str, *, product_ids: list[uuid.UUID]) -> None:
        super().__init__(message)
        self.product_ids = product_ids

    def detail(self) -> dict:
        return {**super().detail(), "product_ids": [str(p) for p in self.product_ids]}


@dataclass(frozen=True)
class PriceChange:
    product_id: uuid.UUID
    previous_unit_price_minor_units: int
    current_unit_price_minor_units: int


class PriceChangedError(CommerceError):
    code = "price_changed"

    def __init__(self, message: str, *, changes: list[PriceChange]) -> None:
        super().__init__(message)
        self.changes = changes

    def detail(self) -> dict:
        return {
            **super().detail(),
            "changes": [
                {
                    "product_id": str(change.product_id),
                    "previous_unit_price_minor_units": change.previous_unit_price_minor_units,
                    "current_unit_price_minor_units": change.current_unit_price_minor_units,
                }
                for change in self.changes
            ],
        }


_NOT_FOUND_CODES = frozenset(
    {
        "cart_not_found",
        "merchant_not_found",
        "product_not_found",
        "cart_item_not_found",
        "checkout_not_found",
    }
)

_STATUS_BY_CODE: dict[str, int] = {
    "invalid_quantity": 422,
    "merchant_mismatch": 422,
    "currency_mismatch": 422,
    "empty_cart": 409,
    "product_unavailable": 409,
    "price_changed": 409,
    "invalid_cart_state": 409,
    "checkout_expired": 409,
    **dict.fromkeys(_NOT_FOUND_CODES, 404),
}


def raise_http_error(exc: CommerceError) -> NoReturn:
    status_code = _STATUS_BY_CODE.get(exc.code, 400)
    raise HTTPException(status_code=status_code, detail=exc.detail()) from exc


def is_not_found(exc: CommerceError) -> bool:
    """Whether `exc` represents a missing resource rather than a conflict —
    used by the agent tool layer to pick the right `Tool` error bucket."""
    return exc.code in _NOT_FOUND_CODES
