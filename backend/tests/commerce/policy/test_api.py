import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from app.commerce.policy import service as policy_service

# --- merchant policy ---


def test_get_merchant_policy_not_configured_returns_404(
    client: TestClient, merchant: Merchant
) -> None:
    response = client.get(f"/api/policy/merchants/{merchant.id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "policy_not_found"


def test_get_merchant_policy_missing_merchant_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/policy/merchants/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "merchant_not_found"


def test_upsert_merchant_policy_creates(client: TestClient, merchant: Merchant) -> None:
    response = client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": 5000, "currency": "USD"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["autonomous_limit_minor_units"] == 5000
    assert body["currency"] == "USD"


def test_upsert_merchant_policy_updates_in_place(client: TestClient, merchant: Merchant) -> None:
    client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": 5000, "currency": "USD"},
    )

    response = client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": 1000, "currency": "USD"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["autonomous_limit_minor_units"] == 1000

    fetched = client.get(f"/api/policy/merchants/{merchant.id}")
    assert fetched.status_code == 200
    assert fetched.json()["version"] == 2


def test_upsert_merchant_policy_malformed_body_returns_422(
    client: TestClient, merchant: Merchant
) -> None:
    response = client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": -1, "currency": "USD"},
    )

    assert response.status_code == 422


# --- evaluate / decision ---


def test_evaluate_checkout(client: TestClient, checkout: Checkout) -> None:
    response = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    assert response.status_code == 200
    body = response.json()
    assert body["checkout_id"] == str(checkout.id)
    assert body["decision"] == "require_authorization"
    assert body["reason"] == "autonomous_limit_exceeded"
    assert body["authorized"] is False


def test_evaluate_checkout_missing_returns_404(client: TestClient) -> None:
    response = client.post(f"/api/policy/checkouts/{uuid.uuid4()}/evaluate")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "checkout_not_found"


def test_evaluate_checkout_is_idempotent_over_http(client: TestClient, checkout: Checkout) -> None:
    first = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")
    second = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    assert first.json()["id"] == second.json()["id"]


def test_get_policy_decision_before_evaluation_returns_404(
    client: TestClient, checkout: Checkout
) -> None:
    response = client.get(f"/api/policy/checkouts/{checkout.id}/decision")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "policy_decision_not_found"


def test_get_policy_decision_after_evaluation(client: TestClient, checkout: Checkout) -> None:
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    response = client.get(f"/api/policy/checkouts/{checkout.id}/decision")

    assert response.status_code == 200
    assert response.json()["checkout_id"] == str(checkout.id)


# --- authorize ---


def test_authorize_checkout(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    db_session.flush()
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    response = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={
            "amount_minor_units": checkout.total_minor_units,
            "currency": checkout.currency,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["checkout_id"] == str(checkout.id)
    assert body["amount_minor_units"] == checkout.total_minor_units

    decision = client.get(f"/api/policy/checkouts/{checkout.id}/decision")
    assert decision.json()["authorized"] is True

    authorization = client.get(f"/api/policy/checkouts/{checkout.id}/authorization")
    assert authorization.status_code == 200
    assert authorization.json()["checkout_id"] == str(checkout.id)


def test_authorize_checkout_before_evaluation_returns_404(
    client: TestClient, checkout: Checkout
) -> None:
    response = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={"amount_minor_units": checkout.total_minor_units, "currency": checkout.currency},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "policy_decision_not_found"


def test_authorize_checkout_wrong_amount_returns_409(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    db_session.flush()
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    response = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={"amount_minor_units": checkout.total_minor_units + 1, "currency": checkout.currency},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "authorization_invalid"


def test_authorize_checkout_twice_returns_409(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=1000, currency="USD"
    )
    db_session.flush()
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")
    client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={"amount_minor_units": checkout.total_minor_units, "currency": checkout.currency},
    )

    response = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={"amount_minor_units": checkout.total_minor_units, "currency": checkout.currency},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_authorized"


def test_authorize_denied_checkout_returns_409(
    client: TestClient, db_session: Session, checkout: Checkout
) -> None:
    checkout.status = "cancelled"
    db_session.flush()
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    response = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={"amount_minor_units": checkout.total_minor_units, "currency": checkout.currency},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "authorization_denied"


def test_get_authorization_before_authorizing_returns_404(
    client: TestClient, checkout: Checkout
) -> None:
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    response = client.get(f"/api/policy/checkouts/{checkout.id}/authorization")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "authorization_required"


def test_authorize_checkout_malformed_body_returns_422(
    client: TestClient, checkout: Checkout
) -> None:
    response = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={"amount_minor_units": "not-an-int", "currency": "USD"},
    )

    assert response.status_code == 422
