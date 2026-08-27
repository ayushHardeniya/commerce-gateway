"""Policy tool available to the AI buyer.

Exactly one capability: ask what policy says about an already-created
checkout. The tool loads the checkout by id and evaluates it through
`app.commerce.policy.service.evaluate_checkout` — the same deterministic
service the HTTP API calls — so Gemini can never supply its own amount to
be evaluated (see `docs/decisions/0006-policy-snapshot-and-explicit-authorization.md`).

There is deliberately no tool here (or anywhere else in `app.agents`) that
can change a merchant's policy, override a decision, or grant a human
authorization. `evaluate_checkout_policy` is read/evaluate-only: it can
return REQUIRE_AUTHORIZATION, but nothing in this module can turn that into
AUTHORIZED. That step exists solely as `app.commerce.policy.service.
authorize_checkout`, reachable only through the HTTP API in
`app.commerce.policy.router` — never through a `Tool`.
"""

import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.agents.tools.base import Tool, ToolConflictError, ToolNotFoundError
from app.commerce.errors import CommerceError, is_not_found
from app.commerce.policy import service as policy_service
from app.commerce.policy.schemas import PolicyDecisionRead, to_policy_decision_read


class EvaluateCheckoutPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkout_id: uuid.UUID


class EvaluateCheckoutPolicyTool(Tool[EvaluateCheckoutPolicyInput, PolicyDecisionRead]):
    name = "evaluate_checkout_policy"
    description = (
        "Evaluate an existing checkout against the merchant's policy and return the "
        "deterministic decision: allow, require_authorization, or deny, plus a "
        "machine-readable reason. Idempotent — re-evaluating an already-evaluated "
        "checkout returns the same decision. This never grants authorization; if the "
        "result is require_authorization, a human must explicitly authorize the "
        "checkout outside of this conversation before anything can proceed."
    )
    input_model = EvaluateCheckoutPolicyInput
    output_model = PolicyDecisionRead

    def __init__(self, db: Session) -> None:
        self._db = db

    def _execute(self, input: EvaluateCheckoutPolicyInput) -> PolicyDecisionRead:
        try:
            decision = policy_service.evaluate_checkout(self._db, input.checkout_id)
        except CommerceError as exc:
            if is_not_found(exc):
                raise ToolNotFoundError(exc.message) from exc
            raise ToolConflictError(exc.message) from exc
        self._db.commit()
        authorization = policy_service.get_authorization(self._db, input.checkout_id)
        return to_policy_decision_read(decision, authorization)
