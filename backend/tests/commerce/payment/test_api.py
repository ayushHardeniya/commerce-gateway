import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from app.commerce.policy import service as policy_service
from tests.commerce.payment.conftest import FakePaymentProvider


def _allow(db_session: Session, merchant: Merchant, checkout: Checkout) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)


def test_initiate_payment(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    _allow(db_session, merchant, checkout)

    response = client.post(f"/api/checkouts/{checkout.id}/payment")

    assert response.status_code == 201
    body = response.json()
    assert body["checkout_id"] == str(checkout.id)
    assert body["provider"] == "razorpay"
    assert body["amount_minor_units"] == checkout.total_minor_units
    assert body["currency"] == checkout.currency
    assert body["razorpay_key_id"] == "rzp_test_fake_key_id"
    assert "provider_order_id" in body


def test_initiate_payment_ignores_caller_supplied_amount_and_currency(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    """There is no request body/param for amount or currency: anything a
    caller tries to smuggle in is simply not consumed by the route."""
    _allow(db_session, merchant, checkout)

    response = client.post(
        f"/api/checkouts/{checkout.id}/payment?amount_minor_units=1&currency=EUR",
        json={"amount_minor_units": 1, "currency": "EUR"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["amount_minor_units"] == checkout.total_minor_units
    assert body["currency"] == checkout.currency


def test_initiate_payment_missing_checkout_returns_404(client: TestClient) -> None:
    response = client.post(f"/api/checkouts/{uuid.uuid4()}/payment")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "checkout_not_found"


def test_initiate_payment_denied_by_currency_mismatch_returns_409(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="EUR"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)

    response = client.post(f"/api/checkouts/{checkout.id}/payment")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "policy_denied"


def test_initiate_payment_without_authorization_returns_404(
    client: TestClient, db_session: Session, checkout: Checkout
) -> None:
    """`authorization_required` reuses the same code (and 404 status) the
    existing `GET /api/policy/checkouts/{id}/authorization` endpoint already
    uses for "not authorized yet" — see `app.commerce.errors`."""
    policy_service.evaluate_checkout(db_session, checkout.id)  # default policy -> require_auth

    response = client.post(f"/api/checkouts/{checkout.id}/payment")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "authorization_required"


def test_confirm_payment_and_complete_checkout(
    client: TestClient,
    db_session: Session,
    merchant: Merchant,
    checkout: Checkout,
    fake_provider: FakePaymentProvider,
) -> None:
    _allow(db_session, merchant, checkout)
    order = client.post(f"/api/checkouts/{checkout.id}/payment").json()
    fake_provider.next_signature_valid = True

    response = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-fake-accepts-it",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["provider_payment_id"] == "pay_fake_1"

    checkout_response = client.get(f"/api/checkouts/{checkout.id}")
    assert checkout_response.json()["status"] == "completed"


def test_confirm_payment_invalid_signature_returns_409_and_checkout_stays_active(
    client: TestClient,
    db_session: Session,
    merchant: Merchant,
    checkout: Checkout,
    fake_provider: FakePaymentProvider,
) -> None:
    _allow(db_session, merchant, checkout)
    order = client.post(f"/api/checkouts/{checkout.id}/payment").json()
    fake_provider.next_signature_valid = False

    response = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "bad-signature",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_payment_signature"

    checkout_response = client.get(f"/api/checkouts/{checkout.id}")
    assert checkout_response.json()["status"] == "active"


def test_confirm_payment_failure_state_survives_request_boundary(
    client: TestClient,
    db_session: Session,
    merchant: Merchant,
    checkout: Checkout,
    fake_provider: FakePaymentProvider,
) -> None:
    """`confirm_payment` flushes `status="failed"` before raising on an
    invalid signature. That write must be committed by the router, not just
    flushed — otherwise it's only visible within the *same* live session,
    and vanishes the moment a request boundary is crossed (`get_db` closes/
    rolls back its session after every real request). `db_session.rollback()`
    here simulates exactly that boundary without needing a second
    connection, since the test session joins the outer transaction via
    SAVEPOINTs (`conftest.py`) — the app's own `commit()` releases a
    savepoint that survives a later `rollback()` to it; a flush alone does
    not."""
    _allow(db_session, merchant, checkout)
    order = client.post(f"/api/checkouts/{checkout.id}/payment").json()
    fake_provider.next_signature_valid = False

    response = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "bad-signature",
        },
    )
    assert response.status_code == 409

    db_session.rollback()

    payment = client.get(f"/api/checkouts/{checkout.id}/payment").json()
    assert payment["status"] == "failed"
    assert payment["failure_code"] == "invalid_payment_signature"


def test_confirm_payment_missing_payment_returns_404(
    client: TestClient, checkout: Checkout
) -> None:
    response = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": "order_x",
            "razorpay_payment_id": "pay_x",
            "razorpay_signature": "sig",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "payment_not_found"


def test_confirm_payment_malformed_body_returns_422(client: TestClient, checkout: Checkout) -> None:
    response = client.post(f"/api/checkouts/{checkout.id}/payment/confirm", json={})

    assert response.status_code == 422


def test_get_payment(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    _allow(db_session, merchant, checkout)
    client.post(f"/api/checkouts/{checkout.id}/payment")

    response = client.get(f"/api/checkouts/{checkout.id}/payment")

    assert response.status_code == 200
    assert response.json()["status"] == "created"


def test_get_payment_missing_returns_404(client: TestClient, checkout: Checkout) -> None:
    response = client.get(f"/api/checkouts/{checkout.id}/payment")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "payment_not_found"
