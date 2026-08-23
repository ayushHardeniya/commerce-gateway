import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.catalog import repository
from app.catalog.schemas import MerchantRead, ProductCatalogView, ProductPage
from app.db.session import get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/merchants", response_model=list[MerchantRead])
def list_merchants(db: Session = Depends(get_db)) -> list[MerchantRead]:
    merchants = repository.list_merchants(db, active_only=True)
    return [MerchantRead.model_validate(merchant) for merchant in merchants]


@router.get("/merchants/{merchant_slug}", response_model=MerchantRead)
def get_merchant(merchant_slug: str, db: Session = Depends(get_db)) -> MerchantRead:
    merchant = repository.get_merchant_by_slug(db, merchant_slug)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return MerchantRead.model_validate(merchant)


@router.get("/merchants/{merchant_slug}/products", response_model=ProductPage)
def list_merchant_products(
    merchant_slug: str,
    q: str | None = Query(default=None, description="Case-insensitive substring match on name."),
    in_stock_only: bool = Query(default=False),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ProductPage:
    merchant = repository.get_merchant_by_slug(db, merchant_slug)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    items, total = repository.search_products(
        db,
        merchant_id=merchant.id,
        query=q,
        active_only=not include_inactive,
        in_stock_only=in_stock_only,
        limit=limit,
        offset=offset,
    )
    return ProductPage(
        items=[ProductCatalogView.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/products", response_model=ProductPage)
def search_products(
    q: str | None = Query(default=None, description="Case-insensitive substring match on name."),
    in_stock_only: bool = Query(default=False),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ProductPage:
    """Merchant-agnostic catalog search — the AI buyer's discovery entry point.

    Searches products across every merchant. Deterministic filtering only: no
    ranking, semantic search, or AI involvement.
    """
    items, total = repository.search_products(
        db,
        query=q,
        active_only=not include_inactive,
        in_stock_only=in_stock_only,
        limit=limit,
        offset=offset,
    )
    return ProductPage(
        items=[ProductCatalogView.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}", response_model=ProductCatalogView)
def get_product(product_id: uuid.UUID, db: Session = Depends(get_db)) -> ProductCatalogView:
    product = repository.get_product_by_id(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductCatalogView.model_validate(product)
