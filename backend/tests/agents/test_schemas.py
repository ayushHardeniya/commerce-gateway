import pytest
from pydantic import ValidationError

from app.agents.schemas import AgentChatRequest, AgentChatResponse, ToolCallRecord


def test_agent_chat_request_accepts_a_valid_message() -> None:
    request = AgentChatRequest(message="Find me ANC headphones under 5000")

    assert request.message == "Find me ANC headphones under 5000"


def test_agent_chat_request_rejects_empty_message() -> None:
    with pytest.raises(ValidationError):
        AgentChatRequest(message="")


def test_agent_chat_request_rejects_overly_long_message() -> None:
    with pytest.raises(ValidationError):
        AgentChatRequest(message="x" * 2001)


def test_agent_chat_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AgentChatRequest(message="hello", extra_field="not allowed")


def test_agent_chat_response_defaults_to_no_tool_calls() -> None:
    response = AgentChatResponse(reply="Here are some options.")

    assert response.tool_calls == []


def test_tool_call_record_error_fields_default_to_none() -> None:
    record = ToolCallRecord(tool_name="search_catalog", arguments={}, ok=True, output={"total": 0})

    assert record.error_code is None
    assert record.error_message is None
