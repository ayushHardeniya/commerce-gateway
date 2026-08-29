import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.commerce.checkout.models import Checkout


def test_create_transaction_records_creation_event(client: TestClient, checkout: Checkout) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.get(f"/api/transactions/{created['id']}/audit-events")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["from_state"] is None
    assert events[0]["to_state"] == "checkout_created"
    assert events[0]["actor_type"] == "system"


def test_audit_events_ordered_after_multiple_transitions(
    client: TestClient, checkout: Checkout
) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "policy_pending"}
    )
    client.post(f"/api/transactions/{created['id']}/transitions", json={"to_state": "cancelled"})

    response = client.get(f"/api/transactions/{created['id']}/audit-events")

    events = response.json()
    assert [e["to_state"] for e in events] == ["checkout_created", "policy_pending", "cancelled"]
    assert [e["sequence"] for e in events] == sorted(e["sequence"] for e in events)


def test_audit_events_missing_transaction_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/transactions/{uuid.uuid4()}/audit-events")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "transaction_not_found"


def test_rejected_transition_does_not_appear_in_audit_history(
    client: TestClient, checkout: Checkout
) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    rejected = client.post(
        f"/api/transactions/{created['id']}/transitions", json={"to_state": "payment_success"}
    )
    assert rejected.status_code == 409

    events = client.get(f"/api/transactions/{created['id']}/audit-events").json()
    assert len(events) == 1  # only the creation event
    assert all(e["to_state"] != "payment_success" for e in events)


def test_transition_with_agent_actor_is_recorded(client: TestClient, checkout: Checkout) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    client.post(
        f"/api/transactions/{created['id']}/transitions",
        json={
            "to_state": "cancelled",
            "actor_type": "agent",
            "actor_id": "buyer-session-1",
            "reason": "buyer asked to stop",
        },
    )

    events = client.get(f"/api/transactions/{created['id']}/audit-events").json()
    assert events[-1]["actor_type"] == "agent"
    assert events[-1]["actor_id"] == "buyer-session-1"
    assert events[-1]["reason"] == "buyer asked to stop"


def test_audit_history_survives_request_boundary(
    client: TestClient, db_session: Session, checkout: Checkout
) -> None:
    """Mirrors the payment/transaction suites' own boundary tests: each HTTP
    call through `client` commits, so a `db_session.rollback()` afterward
    must not erase audit rows written by an earlier request."""
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    client.post(f"/api/transactions/{created['id']}/transitions", json={"to_state": "cancelled"})

    db_session.rollback()

    events = client.get(f"/api/transactions/{created['id']}/audit-events").json()
    assert [e["to_state"] for e in events] == ["checkout_created", "cancelled"]
