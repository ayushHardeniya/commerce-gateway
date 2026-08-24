from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agents.buyer import (
    AgentConfigurationError,
    AgentIterationLimitExceeded,
    AgentProviderError,
    AIBuyerService,
)
from app.agents.router import get_ai_buyer_service
from app.agents.schemas import AgentChatResponse, ToolCallRecord
from app.core.config import Settings
from app.main import app


class _StubService:
    def __init__(self, result=None, error=None) -> None:
        self._result = result
        self._error = error

    def chat(self, message: str):
        if self._error is not None:
            raise self._error
        return self._result


def _override(stub: _StubService):
    app.dependency_overrides[get_ai_buyer_service] = lambda: stub


def _clear_override() -> None:
    app.dependency_overrides.pop(get_ai_buyer_service, None)


def test_chat_endpoint_returns_agent_response(client: TestClient, db_session: Session) -> None:
    stub = _StubService(
        result=AgentChatResponse(
            reply="Here's a great pair of ANC headphones.",
            tool_calls=[
                ToolCallRecord(
                    tool_name="search_catalog",
                    arguments={"query": "ANC headphones"},
                    ok=True,
                    output={"total": 1},
                )
            ],
        )
    )
    _override(stub)
    try:
        response = client.post("/api/agent/chat", json={"message": "Find me ANC headphones"})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Here's a great pair of ANC headphones."
    assert body["tool_calls"][0]["tool_name"] == "search_catalog"


def test_chat_endpoint_rejects_empty_message(client: TestClient) -> None:
    response = client.post("/api/agent/chat", json={"message": ""})

    assert response.status_code == 422


def test_chat_endpoint_rejects_missing_message_field(client: TestClient) -> None:
    response = client.post("/api/agent/chat", json={})

    assert response.status_code == 422


def test_chat_endpoint_returns_503_when_not_configured(client: TestClient) -> None:
    stub = _StubService(error=AgentConfigurationError("GEMINI_API_KEY is not configured."))
    _override(stub)
    try:
        response = client.post("/api/agent/chat", json={"message": "hello"})
    finally:
        _clear_override()

    assert response.status_code == 503


def test_chat_endpoint_returns_422_when_iteration_limit_exceeded(client: TestClient) -> None:
    stub = _StubService(error=AgentIterationLimitExceeded("iteration limit exceeded"))
    _override(stub)
    try:
        response = client.post("/api/agent/chat", json={"message": "hello"})
    finally:
        _clear_override()

    assert response.status_code == 422


def test_chat_endpoint_returns_502_on_provider_error(client: TestClient) -> None:
    stub = _StubService(error=AgentProviderError("Gemini request failed"))
    _override(stub)
    try:
        response = client.post("/api/agent/chat", json={"message": "hello"})
    finally:
        _clear_override()

    assert response.status_code == 502


def test_chat_endpoint_fails_clearly_end_to_end_without_gemini_api_key(
    client: TestClient, db_session: Session
) -> None:
    """Exercises the real `AIBuyerService` (not a stub) through the router:
    with no Gemini configuration, the request must fail with a clear 503,
    not a fabricated reply and not an unhandled exception."""
    unconfigured_service = AIBuyerService(
        db_session, settings=Settings(_env_file=None, gemini_api_key=None)
    )
    app.dependency_overrides[get_ai_buyer_service] = lambda: unconfigured_service
    try:
        response = client.post("/api/agent/chat", json={"message": "Find me headphones"})
    finally:
        _clear_override()

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_app_starts_and_serves_other_routes_without_gemini_configured(
    client: TestClient,
) -> None:
    """The app as a whole must not require GEMINI_API_KEY to start or to serve
    unrelated routes — only the agent endpoint itself depends on it."""
    response = client.get("/health")

    assert response.status_code == 200
