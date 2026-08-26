"""HTTP API for cart management, under `/api/carts`.

Thin: every endpoint just calls into `app.commerce.cart.service` and maps
`CommerceError` to a structured HTTP error via
`app.commerce.errors.raise_http_error`. No business rule lives here.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.commerce.cart import service
from app.commerce.cart.models import Cart
from app.commerce.cart.schemas import (
    AddCartItemRequest,
    CartRead,
    CreateCartRequest,
    UpdateCartItemRequest,
)
from app.commerce.errors import CommerceError, raise_http_error
from app.db.session import get_db

router = APIRouter(prefix="/api/carts", tags=["cart"])


def _read(cart: Cart) -> CartRead:
    return CartRead.model_validate(cart)


@router.post("", response_model=CartRead, status_code=status.HTTP_201_CREATED)
def create_cart(request: CreateCartRequest, db: Session = Depends(get_db)) -> CartRead:
    try:
        cart = service.create_cart(db, merchant_id=request.merchant_id)
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return _read(cart)


@router.get("/{cart_id}", response_model=CartRead)
def get_cart(cart_id: uuid.UUID, db: Session = Depends(get_db)) -> CartRead:
    try:
        cart = service.get_cart(db, cart_id)
    except CommerceError as exc:
        raise_http_error(exc)
    return _read(cart)


@router.post("/{cart_id}/items", response_model=CartRead, status_code=status.HTTP_201_CREATED)
def add_item(
    cart_id: uuid.UUID, request: AddCartItemRequest, db: Session = Depends(get_db)
) -> CartRead:
    try:
        cart = service.add_item(
            db, cart_id=cart_id, product_id=request.product_id, quantity=request.quantity
        )
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return _read(cart)


@router.patch("/{cart_id}/items/{item_id}", response_model=CartRead)
def update_item_quantity(
    cart_id: uuid.UUID,
    item_id: uuid.UUID,
    request: UpdateCartItemRequest,
    db: Session = Depends(get_db),
) -> CartRead:
    try:
        cart = service.update_item_quantity(
            db, cart_id=cart_id, item_id=item_id, quantity=request.quantity
        )
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return _read(cart)


@router.delete("/{cart_id}/items/{item_id}", response_model=CartRead)
def remove_item(cart_id: uuid.UUID, item_id: uuid.UUID, db: Session = Depends(get_db)) -> CartRead:
    try:
        cart = service.remove_item(db, cart_id=cart_id, item_id=item_id)
    except CommerceError as exc:
        raise_http_error(exc)
    db.commit()
    return _read(cart)
