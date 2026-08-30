import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog.models import Merchant, Product
from app.commerce.checkout.models import Checkout
from app.commerce.policy import service as policy_service
from tests.commerce.payment.conftest import FakePaymentProvider


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
    first = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.post("/api/transactions", json={"checkout_id": str(checkout.id)})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "transaction_already_exists"
    # Structured, not just embedded in the message — a caller (the frontend,
    # the AI buyer's own recovery logic) can recover the existing
    # transaction without parsing free text.
    assert detail["transaction_id"] == first["id"]


# --- GET /api/transactions/by-checkout/{checkout_id} ---


def test_get_transaction_by_checkout(client: TestClient, checkout: Checkout) -> None:
    created = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.get(f"/api/transactions/by-checkout/{checkout.id}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_transaction_by_checkout_missing_returns_404(
    client: TestClient, checkout: Checkout
) -> None:
    """A real checkout with no transaction yet — distinct from a checkout id
    that doesn't exist at all, which this endpoint doesn't distinguish
    (it never loads the checkout, only queries transactions by checkout id;
    both cases mean "nothing to recover here")."""
    response = client.get(f"/api/transactions/by-checkout/{checkout.id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "transaction_not_found"


def test_get_transaction_by_checkout_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/transactions/by-checkout/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "transaction_not_found"


# --- GET /api/transactions (listing) ---


def test_list_transactions_empty(client: TestClient) -> None:
    response = client.get("/api/transactions")

    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_transactions_returns_newest_first(client: TestClient, checkout: Checkout) -> None:
    first = client.post("/api/transactions", json={}).json()
    second = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()

    response = client.get("/api/transactions")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    ids = [item["id"] for item in body["items"]]
    assert ids == [second["id"], first["id"]]


def test_list_transactions_pagination(client: TestClient) -> None:
    created = [client.post("/api/transactions", json={}).json() for _ in range(3)]

    first_page = client.get("/api/transactions?limit=2&offset=0").json()
    second_page = client.get("/api/transactions?limit=2&offset=2").json()

    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
    all_ids = {item["id"] for item in first_page["items"] + second_page["items"]}
    assert all_ids == {t["id"] for t in created}


def test_list_transactions_limit_is_bounded(client: TestClient) -> None:
    response = client.get("/api/transactions?limit=0")
    assert response.status_code == 422

    response = client.get("/api/transactions?limit=101")
    assert response.status_code == 422


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


# --- M8A: full lifecycle / cross-domain boundary tests ---
#
# Everything below drives the real application boundary — cart, checkout,
# policy, payment, and transaction — entirely through the HTTP API, the way
# a real client actually would. Payment goes through the existing
# `FakePaymentProvider` test double (see `conftest.py`'s `client` override
# in this directory); nothing here ever calls real Razorpay or Gemini.


def test_full_http_lifecycle_allow_to_order_confirmed(
    client: TestClient,
    db_session: Session,
    merchant: Merchant,
    checkout: Checkout,
    fake_provider: FakePaymentProvider,
) -> None:
    """ALLOW path, start to finish, over the real API: checkout already
    exists (fixture) -> policy evaluates to `allow` -> transaction walks
    checkout_created -> policy_pending -> authorized -> payment_pending ->
    payment_success -> order_confirmed, with a real (fake-provider-backed)
    payment initiated and confirmed along the way, and the checkout itself
    ending up `completed`."""
    _allow(db_session, merchant, checkout)

    tx = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    tx_id = tx["id"]
    assert tx["state"] == "checkout_created"

    client.post(f"/api/transactions/{tx_id}/transitions", json={"to_state": "policy_pending"})
    authorized = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "authorized"}
    )
    assert authorized.json()["state"] == "authorized"

    order = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert order.status_code == 201
    pending = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "payment_pending"}
    )
    assert pending.json()["state"] == "payment_pending"

    fake_provider.next_signature_valid = True
    payment = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order.json()["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-fake-accepts-it",
        },
    )
    assert payment.json()["status"] == "success"

    success = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "payment_success"}
    )
    assert success.json()["state"] == "payment_success"
    confirmed = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "order_confirmed"}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "order_confirmed"

    assert client.get(f"/api/checkouts/{checkout.id}").json()["status"] == "completed"

    events = client.get(f"/api/transactions/{tx_id}/audit-events").json()
    assert [e["to_state"] for e in events] == [
        "checkout_created",
        "policy_pending",
        "authorized",
        "payment_pending",
        "payment_success",
        "order_confirmed",
    ]


def test_full_http_lifecycle_require_authorization_to_order_confirmed(
    client: TestClient,
    checkout: Checkout,
    fake_provider: FakePaymentProvider,
) -> None:
    """REQUIRE_AUTHORIZATION path, start to finish: default policy (no
    explicit `MerchantPolicy` -> autonomous limit 0) forces
    `require_authorization`; payment is proven unreachable until a human
    authorizes; authorizing then unblocks both the transaction's own
    `-> authorized` transition and payment initiation, and the transaction
    still reaches `order_confirmed` exactly like the ALLOW path."""
    decision = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate").json()
    assert decision["decision"] == "require_authorization"

    tx = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    tx_id = tx["id"]
    client.post(f"/api/transactions/{tx_id}/transitions", json={"to_state": "policy_pending"})

    # Cannot proceed as paid without authorization — neither leg of it.
    blocked_transition = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "authorized"}
    )
    assert blocked_transition.status_code == 409
    blocked_payment = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert blocked_payment.status_code == 404
    assert blocked_payment.json()["detail"]["code"] == "authorization_required"

    authorize = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={
            "amount_minor_units": checkout.total_minor_units,
            "currency": checkout.currency,
        },
    )
    assert authorize.status_code == 201

    authorized = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "authorized"}
    )
    assert authorized.json()["state"] == "authorized"

    order = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert order.status_code == 201
    client.post(f"/api/transactions/{tx_id}/transitions", json={"to_state": "payment_pending"})

    fake_provider.next_signature_valid = True
    payment = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order.json()["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-fake-accepts-it",
        },
    )
    assert payment.json()["status"] == "success"

    client.post(f"/api/transactions/{tx_id}/transitions", json={"to_state": "payment_success"})
    confirmed = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "order_confirmed"}
    )
    assert confirmed.json()["state"] == "order_confirmed"

    events = client.get(f"/api/transactions/{tx_id}/audit-events").json()
    assert [e["to_state"] for e in events] == [
        "checkout_created",
        "policy_pending",
        "authorized",
        "payment_pending",
        "payment_success",
        "order_confirmed",
    ]
    # The `authorized` event's own metadata reflects the real decision it
    # was granted against, not a caller's claim about it.
    authorized_event = events[2]
    assert authorized_event["event_metadata"]["policy_decision"] == "require_authorization"


def test_deny_decision_blocks_every_domain_and_leaves_a_consistent_audit_trail(
    client: TestClient, db_session: Session, merchant: Merchant, checkout: Checkout
) -> None:
    """The cross-domain boundary: one `deny` decision, proven unbypassable
    from every angle a caller could try it — payment initiation, the
    transaction's own `-> authorized` transition, and (implicitly) any
    further progress at all. Deliberately doesn't re-walk every way a
    decision can end up `deny` (`tests/commerce/policy` already does that in
    depth) — only that once it is, nothing downstream can route around it."""
    # A currency-mismatched policy is the one way to get a real `deny` on an
    # otherwise-active checkout (same technique already used elsewhere in
    # this file/`app.commerce.payment.test_service`).
    policy_service.upsert_policy(
        db_session, merchant_id=merchant.id, autonomous_limit_minor_units=5000, currency="EUR"
    )
    decision = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate").json()
    assert decision["decision"] == "deny"

    payment_attempt = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert payment_attempt.status_code == 409
    assert payment_attempt.json()["detail"]["code"] == "policy_denied"

    tx = client.post("/api/transactions", json={"checkout_id": str(checkout.id)}).json()
    tx_id = tx["id"]
    client.post(f"/api/transactions/{tx_id}/transitions", json={"to_state": "policy_pending"})

    authorize_attempt = client.post(
        f"/api/transactions/{tx_id}/transitions", json={"to_state": "authorized"}
    )
    assert authorize_attempt.status_code == 409

    # No route to a paid/confirmed outcome exists from here: the FSM has no
    # edge from `policy_pending` to `payment_pending`/`payment_success`/
    # `order_confirmed` at all (proven structurally elsewhere), and the one
    # edge that matters for this scenario — `-> authorized` — is the one
    # just rejected above. The transaction is left exactly where it was.
    final = client.get(f"/api/transactions/{tx_id}").json()
    assert final["state"] == "policy_pending"

    no_payment = client.get(f"/api/checkouts/{checkout.id}/payment")
    assert no_payment.status_code == 404
    assert no_payment.json()["detail"]["code"] == "payment_not_found"

    events = client.get(f"/api/transactions/{tx_id}/audit-events").json()
    assert [e["to_state"] for e in events] == ["checkout_created", "policy_pending"]


def test_checkout_can_still_be_paid_after_its_product_is_deleted(
    client: TestClient,
    db_session: Session,
    merchant: Merchant,
    product: Product,
    checkout: Checkout,
    fake_provider: FakePaymentProvider,
) -> None:
    """`CheckoutItem` denormalizes product name/sku/price at checkout-
    creation time (`docs/decisions/0005-cart-price-snapshot.md`) precisely
    so a checkout stays a complete, payable record even if its product is
    later removed — `CheckoutItem.product_id` is `ON DELETE SET NULL`, not
    a hard requirement. `test_deleting_product_sets_checkout_item_product_id_null`
    already proves the FK goes null at the DB level; this proves the
    stronger, product-independent invariant it exists for: the checkout can
    still be paid to a real (fake-provider) success afterward."""
    product_name = product.name
    _allow(db_session, merchant, checkout)

    db_session.delete(product)
    db_session.flush()

    order = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert order.status_code == 201

    fake_provider.next_signature_valid = True
    payment = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order.json()["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-fake-accepts-it",
        },
    )
    assert payment.status_code == 200
    assert payment.json()["status"] == "success"

    checkout_after = client.get(f"/api/checkouts/{checkout.id}").json()
    assert checkout_after["status"] == "completed"
    assert checkout_after["items"][0]["product_id"] is None
    assert checkout_after["items"][0]["product_name"] == product_name
