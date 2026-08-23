import uuid

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product


def test_create_and_retrieve_merchant(db_session: Session) -> None:
    merchant = Merchant(name="Acme Co", slug="acme-co", description="desc")
    db_session.add(merchant)
    db_session.flush()

    fetched = db_session.get(Merchant, merchant.id)

    assert fetched is not None
    assert fetched.name == "Acme Co"
    assert fetched.slug == "acme-co"
    assert fetched.active is True
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


def test_merchant_slug_must_be_unique(db_session: Session) -> None:
    db_session.add(Merchant(name="Acme", slug="acme"))
    db_session.flush()

    db_session.add(Merchant(name="Acme Duplicate", slug="acme"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_merchant_blank_name_rejected(db_session: Session) -> None:
    db_session.add(Merchant(name="   ", slug="blank-name"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_create_and_retrieve_product(db_session: Session, merchant: Merchant) -> None:
    product = Product(
        merchant_id=merchant.id,
        sku="SKU-1",
        name="Widget",
        price_minor_units=1234,
        currency="USD",
        stock_quantity=5,
    )
    db_session.add(product)
    db_session.flush()

    fetched = db_session.get(Product, product.id)

    assert fetched is not None
    assert fetched.merchant_id == merchant.id
    assert fetched.price_minor_units == 1234
    assert fetched.active is True


def test_product_merchant_relationship(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    assert product.merchant.id == merchant.id
    assert product in merchant.products


def test_product_sku_unique_per_merchant(
    db_session: Session, merchant: Merchant, product: Product
) -> None:
    duplicate = Product(
        merchant_id=merchant.id,
        sku=product.sku,
        name="Duplicate SKU widget",
        price_minor_units=100,
        currency="USD",
        stock_quantity=1,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_sku_allowed_across_different_merchants(
    db_session: Session, merchant: Merchant
) -> None:
    other_merchant = Merchant(name="Other Co", slug="other-co")
    db_session.add(other_merchant)
    db_session.flush()

    product_a = Product(
        merchant_id=merchant.id,
        sku="SHARED-SKU",
        name="A",
        price_minor_units=100,
        currency="USD",
        stock_quantity=1,
    )
    product_b = Product(
        merchant_id=other_merchant.id,
        sku="SHARED-SKU",
        name="B",
        price_minor_units=200,
        currency="USD",
        stock_quantity=1,
    )
    db_session.add_all([product_a, product_b])
    db_session.flush()

    assert product_a.id != product_b.id


def test_negative_price_rejected(db_session: Session, merchant: Merchant) -> None:
    product = Product(
        merchant_id=merchant.id,
        sku="BAD-PRICE",
        name="Bad price",
        price_minor_units=-1,
        currency="USD",
        stock_quantity=1,
    )
    db_session.add(product)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_negative_stock_rejected(db_session: Session, merchant: Merchant) -> None:
    product = Product(
        merchant_id=merchant.id,
        sku="BAD-STOCK",
        name="Bad stock",
        price_minor_units=100,
        currency="USD",
        stock_quantity=-1,
    )
    db_session.add(product)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("currency", ["US", "usd"])
def test_invalid_currency_code_rejected_by_check_constraint(
    db_session: Session, merchant: Merchant, currency: str
) -> None:
    product = Product(
        merchant_id=merchant.id,
        sku=f"BAD-CCY-{currency}",
        name="Bad currency",
        price_minor_units=100,
        currency=currency,
        stock_quantity=1,
    )
    db_session.add(product)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_currency_longer_than_column_rejected(db_session: Session, merchant: Merchant) -> None:
    product = Product(
        merchant_id=merchant.id,
        sku="BAD-CCY-USDX",
        name="Bad currency",
        price_minor_units=100,
        currency="USDX",
        stock_quantity=1,
    )
    db_session.add(product)

    with pytest.raises(DataError):
        db_session.flush()


def test_product_requires_existing_merchant(db_session: Session) -> None:
    orphan = Product(
        merchant_id=uuid.uuid4(),
        sku="ORPHAN",
        name="Orphan product",
        price_minor_units=100,
        currency="USD",
        stock_quantity=1,
    )
    db_session.add(orphan)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_price_is_stored_as_exact_integer_not_float(db_session: Session, product: Product) -> None:
    assert isinstance(product.price_minor_units, int)
    assert not isinstance(product.price_minor_units, float)
    assert product.price_minor_units == 1000


@pytest.mark.parametrize(
    ("active", "stock_quantity", "merchant_active", "expected"),
    [
        (True, 5, True, True),
        (True, 0, True, False),
        (False, 5, True, False),
        (True, 5, False, False),
        (False, 0, False, False),
    ],
)
def test_is_available_reflects_product_stock_and_merchant_state(
    db_session: Session,
    active: bool,
    stock_quantity: int,
    merchant_active: bool,
    expected: bool,
) -> None:
    merchant = Merchant(name="Matrix Co", slug="matrix-co", active=merchant_active)
    db_session.add(merchant)
    db_session.flush()

    product = Product(
        merchant_id=merchant.id,
        sku="MATRIX-1",
        name="Matrix product",
        price_minor_units=100,
        currency="USD",
        stock_quantity=stock_quantity,
        active=active,
    )
    db_session.add(product)
    db_session.flush()
    db_session.refresh(product)

    assert product.is_available is expected
