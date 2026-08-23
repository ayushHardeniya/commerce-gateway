"""Deterministic demo catalog data for local development.

Not used by the test suite (tests build their own fixtures) — this exists
solely so a developer can run `uv run python -m app.catalog.seed` against a
local database and have something realistic to look at through the API.

IDs are derived deterministically from a fixed namespace so re-running the
seed against the same database upserts the same rows instead of duplicating
them.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product

_NAMESPACE = uuid.UUID("6f6d5c9a-9b0b-4c3a-8a2e-2b6a2f9e6b41")


def _deterministic_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, ".".join(parts))


@dataclass(frozen=True)
class SeedProduct:
    sku: str
    name: str
    description: str
    price_minor_units: int
    currency: str
    stock_quantity: int
    active: bool = True


@dataclass(frozen=True)
class SeedMerchant:
    slug: str
    name: str
    description: str
    products: list[SeedProduct] = field(default_factory=list)


SEED_MERCHANTS: list[SeedMerchant] = [
    SeedMerchant(
        slug="northwind-electronics",
        name="Northwind Electronics",
        description="Consumer electronics and accessories.",
        products=[
            SeedProduct(
                sku="NW-HEAD-01",
                name="Wireless Headphones",
                description="Over-ear wireless headphones with active noise cancellation.",
                price_minor_units=4999,
                currency="USD",
                stock_quantity=25,
            ),
            SeedProduct(
                sku="NW-CHRG-02",
                name="USB-C Fast Charger",
                description="65W USB-C GaN charger with a single port.",
                price_minor_units=1999,
                currency="USD",
                stock_quantity=100,
            ),
            SeedProduct(
                sku="NW-CAM-03",
                name="4K Action Camera",
                description="Waterproof action camera with 4K/60fps recording.",
                price_minor_units=12999,
                currency="USD",
                stock_quantity=0,
            ),
        ],
    ),
    SeedMerchant(
        slug="terra-home-goods",
        name="Terra Home Goods",
        description="Everyday goods for the home.",
        products=[
            SeedProduct(
                sku="TH-MUG-01",
                name="Ceramic Coffee Mug",
                description="12oz glazed ceramic mug, dishwasher safe.",
                price_minor_units=1499,
                currency="USD",
                stock_quantity=200,
            ),
            SeedProduct(
                sku="TH-LAMP-02",
                name="Adjustable Desk Lamp",
                description="LED desk lamp with three brightness levels.",
                price_minor_units=3499,
                currency="USD",
                stock_quantity=40,
            ),
            SeedProduct(
                sku="TH-CAND-03",
                name="Scented Soy Candle",
                description="Discontinued seasonal candle, kept for order history only.",
                price_minor_units=999,
                currency="USD",
                stock_quantity=60,
                active=False,
            ),
        ],
    ),
]


def seed_demo_catalog(db: Session) -> None:
    for seed_merchant in SEED_MERCHANTS:
        merchant_id = _deterministic_id("merchant", seed_merchant.slug)
        merchant = db.get(Merchant, merchant_id)
        if merchant is None:
            merchant = Merchant(id=merchant_id, slug=seed_merchant.slug)
            db.add(merchant)

        merchant.name = seed_merchant.name
        merchant.description = seed_merchant.description
        merchant.active = True

        for seed_product in seed_merchant.products:
            product_id = _deterministic_id("product", seed_merchant.slug, seed_product.sku)
            product = db.get(Product, product_id)
            if product is None:
                product = Product(id=product_id, merchant_id=merchant_id, sku=seed_product.sku)
                db.add(product)

            product.merchant_id = merchant_id
            product.name = seed_product.name
            product.description = seed_product.description
            product.price_minor_units = seed_product.price_minor_units
            product.currency = seed_product.currency
            product.stock_quantity = seed_product.stock_quantity
            product.active = seed_product.active

    db.commit()


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        seed_demo_catalog(db)
    print(
        f"Seeded {sum(len(m.products) for m in SEED_MERCHANTS)} products "
        f"across {len(SEED_MERCHANTS)} merchants."
    )


if __name__ == "__main__":
    main()
