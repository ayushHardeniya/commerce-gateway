import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from app.commerce.policy import service as policy_service


def test_create_transaction_discovered(client: TestClient) -> None:
    response = client.post("/api/transactions", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "discovered"
    assert body["cart_id"] is None
    assert body["checkout_id"] is None


def test_create_transaction_from_checkout(client: TestClient, checkout: Checkout) -> None:
    response = client.post("/api/transactions", json={"checkout_id": str(checkout.id)})

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "checkout_created"
    assert body["checkout_id"] == str(checkout.id)
    assert body["cart_id"] == str(checkout.cart_id)


def test_create_transaction_missing_checkout_returns_404(client: TestClient) -> None:
    response = client.post("/api/transactions", json={"checkout_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "checkout_not_found"


def test_create_transaction_duplicate_checkout_returns_409(
    client: TestClient, checkout: Checkout
) -> None:
    client.post("/api/transactions", json={"checkout_id": str(checkout.id)})

    response = client.post("/api/transactions", json={"checkout_id": str(checkout.id)})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "checkout_already_has_transaction"


def test_get_transaction(client: TestClient, checkout: Checkout) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.get(f"/api/transactions/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_transaction_missing_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/transactions/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "transaction_not_found"


def test_transition_transaction_valid(client: TestClient, checkout: Checkout) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "policy_pending"}
    )

    assert response.status_code == 200
    assert response.json()["state"] == "policy_pending"


def test_transition_transaction_invalid_edge_returns_409(
    client: TestClient, checkout: Checkout
) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "payment_success"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_transaction_transition"


def test_transition_transaction_unguarded_claim_of_authorization_rejected(
    client: TestClient, db_session: Session, checkout: Checkout
) -> None:
    """A caller (including an AI buyer, if one ever tried) cannot assert its
    way into 'authorized' without a real ALLOW/authorized `PolicyDecision` —
    the transition is rejected exactly like any other invalid one."""
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "policy_pending"}
    )

    response = client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "authorized"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_transaction_transition"


def test_transition_transaction_missing_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/api/transactions/{uuid.uuid4()}/transitions", json={"to_state": "cancelled"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "transaction_not_found"


def test_transition_transaction_malformed_body_returns_422(
    client: TestClient, checkout: Checkout
) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.post(f"/api/transactions/{created['id']}/transitions", json={})

    assert response.status_code == 422


def test_terminal_state_persists_across_request_boundary(
    client: TestClient, db_session: Session, checkout: Checkout
) -> None:
    """Mirrors `test_confirm_payment_failure_state_survives_request_boundary`
    in the payment suite: each HTTP call through `client` commits, so a
    `db_session.rollback()` afterward (undoing anything left merely flushed)
    must not erase the transaction's persisted state."""
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    client.post(f"/api/transactions/{created['id']}/transitions", json={"to_state": "cancelled"})

    db_session.rollback()

    response = client.get(f"/api/transactions/{created['id']}")
    assert response.json()["state"] == "cancelled"

    again = client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "failed"}
    )
    assert again.status_code == 409


def _allow(db_session: Session, merchant: Merchant, checkout: Checkout) -> None:
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="USD"
    )
    policy_service.evaluate_checkout(db_session, checkout.id)


def test_transition_transaction_through_policy_allow(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    _allow(db_session, merchant, checkout)
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "policy_pending"}
    )

    response = client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "authorized"}
    )

    assert response.status_code == 200
    assert response.json()["state"] == "authorized"
