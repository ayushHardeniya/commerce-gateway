"""M9B regression: the real application never called `transition_transaction`
anywhere except from within `app.commerce.transaction` itself, so a real
`Transaction` sat frozen at `checkout_created` forever, even after its
checkout was fully paid — a demo/deployment bug, not a security one (the
FSM's guards were always correct; nothing ever *drove* them). See the M9B
audit and `app.commerce.policy.service`/`app.commerce.payment.service`'s
`sync_transaction_state`/`_sync_transaction_after_decision` call sites for
the fix.

Every test below reproduces the actual, real-application call sequence —
create a checkout, attach a `Transaction` to it the way the AI-buyer chat
frontend does (`POST /api/transactions` right after `create_checkout`), then
drive policy/authorization/payment purely through their own real HTTP
endpoints — and never once calls `POST /api/transactions/{id}/transitions`
directly. That is the point: unlike
`tests/commerce/transaction/test_api.py`'s `test_full_http_lifecycle_*`
tests (which exercise the FSM's guards directly, by design), these tests
prove the *wiring* — that policy/authorization/payment actions alone are
now sufficient to carry the transaction all the way to its correct outcome,
with no separate caller driving it.
"""

from fastapi.testclient import TestClient

from app.catalog.models import Merchant
from app.commerce.checkout.models import Checkout
from tests.commerce.payment.conftest import FakePaymentProvider


def _link_transaction(client: TestClient, checkout_id: str) -> str:
    """Mirrors `frontend/src/app/page.tsx`'s `maybeLinkTransaction`: the one
    real call site that attaches a `Transaction` to a checkout today."""
    response = client.post("/api/transactions", json={"checkout_id": checkout_id})
    assert response.status_code == 201
    return response.json()["id"]


def test_allow_checkout_reaches_order_confirmed_with_no_manual_transition(
    client: TestClient, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    """The ALLOW path: evaluating policy, then initiating and confirming
    payment — three real, independent HTTP calls a real client would make —
    is enough on its own to carry the transaction from `checkout_created`
    all the way to `order_confirmed`, including the intermediate
    `policy_pending`/`authorized`/`payment_pending`/`payment_success` steps,
    each recorded as its own audit event."""
    client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": 5000, "currency": "USD"},
    )
    tx_id = _link_transaction(client, str(checkout.id))
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "checkout_created"

    decision = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate").json()
    assert decision["decision"] == "allow"
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "authorized"

    order = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert order.status_code == 201
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "payment_pending"

    fake_provider.next_signature_valid = True
    confirm = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order.json()["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-fake-accepts-it",
        },
    )
    assert confirm.json()["status"] == "success"

    final = client.get(f"/api/transactions/{tx_id}").json()
    assert final["state"] == "order_confirmed"

    events = client.get(f"/api/transactions/{tx_id}/audit-events").json()
    assert [e["to_state"] for e in events] == [
        "checkout_created",
        "policy_pending",
        "authorized",
        "payment_pending",
        "payment_success",
        "order_confirmed",
    ]


def test_require_authorization_checkout_reaches_order_confirmed_with_no_manual_transition(
    client: TestClient, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    """The REQUIRE_AUTHORIZATION path: no `MerchantPolicy` configured (the
    safe default, autonomous limit 0) forces `require_authorization`, so the
    transaction stalls at `policy_pending` on its own — correctly — until a
    human calls the real `authorize_checkout` endpoint, at which point it
    (and payment, afterward) proceed exactly as the ALLOW path does above."""
    tx_id = _link_transaction(client, str(checkout.id))

    decision = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate").json()
    assert decision["decision"] == "require_authorization"
    stalled = client.get(f"/api/transactions/{tx_id}").json()
    assert stalled["state"] == "policy_pending"

    # Payment is genuinely unreachable while unauthorized — no transaction
    # wiring involved, this is `payment.service`'s own eligibility check.
    blocked = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert blocked.status_code == 404
    assert blocked.json()["detail"]["code"] == "authorization_required"

    authorize = client.post(
        f"/api/policy/checkouts/{checkout.id}/authorize",
        json={
            "amount_minor_units": checkout.total_minor_units,
            "currency": checkout.currency,
        },
    )
    assert authorize.status_code == 201
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "authorized"

    order = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert order.status_code == 201
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "payment_pending"

    fake_provider.next_signature_valid = True
    confirm = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order.json()["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-fake-accepts-it",
        },
    )
    assert confirm.json()["status"] == "success"
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "order_confirmed"


def test_deny_decision_leaves_transaction_at_policy_denied_with_no_manual_transition(
    client: TestClient, merchant: Merchant, checkout: Checkout
) -> None:
    """The DENY path: a currency-mismatched policy is the one way to get a
    real `deny` on an otherwise-active checkout. Evaluating it alone is
    enough to carry the transaction from `checkout_created` to
    `policy_denied` — there is no HTTP action a human or the AI buyer could
    ever take that reaches `authorized`, `payment_pending`, or beyond from
    here, and no manual transition call is involved in proving it."""
    client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": 5000, "currency": "EUR"},
    )
    tx_id = _link_transaction(client, str(checkout.id))

    decision = client.post(f"/api/policy/checkouts/{checkout.id}/evaluate").json()
    assert decision["decision"] == "deny"

    final = client.get(f"/api/transactions/{tx_id}").json()
    assert final["state"] == "policy_denied"
    assert final["failure_reason"] == "currency_mismatch"

    blocked = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "policy_denied"

    events = client.get(f"/api/transactions/{tx_id}/audit-events").json()
    assert [e["to_state"] for e in events] == [
        "checkout_created",
        "policy_pending",
        "policy_denied",
    ]


def test_payment_signature_failure_leaves_transaction_at_payment_failed_with_no_manual_transition(
    client: TestClient, merchant: Merchant, checkout: Checkout, fake_provider: FakePaymentProvider
) -> None:
    """A real (fake-provider) invalid-signature rejection alone is enough to
    carry the transaction from `payment_pending` to `payment_failed`, with
    the guard's own domain-derived `failure_reason` — no manual transition
    call involved."""
    client.put(
        f"/api/policy/merchants/{merchant.id}",
        json={"autonomous_limit_minor_units": 5000, "currency": "USD"},
    )
    tx_id = _link_transaction(client, str(checkout.id))
    client.post(f"/api/policy/checkouts/{checkout.id}/evaluate")

    order = client.post(f"/api/checkouts/{checkout.id}/payment")
    assert order.status_code == 201
    assert client.get(f"/api/transactions/{tx_id}").json()["state"] == "payment_pending"

    fake_provider.next_signature_valid = False
    confirm = client.post(
        f"/api/checkouts/{checkout.id}/payment/confirm",
        json={
            "razorpay_order_id": order.json()["provider_order_id"],
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "not-the-real-signature",
        },
    )
    assert confirm.status_code == 409

    failed = client.get(f"/api/transactions/{tx_id}").json()
    assert failed["state"] == "payment_failed"
    assert failed["failure_reason"] == "invalid_payment_signature"
