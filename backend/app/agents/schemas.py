"""Request/response contract for the AI buyer chat endpoint.

`ToolCallRecord`/`AgentChatResponse` double as the agent loop's own result
type in `app.agents.buyer` — there is no separate internal shape to keep in
sync with what the API returns.
"""

from pydantic import BaseModel, ConfigDict, Field


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        min_length=1, max_length=2000, description="The user's natural-language shopping request."
    )


class ToolCallRecord(BaseModel):
    """One tool call the agent made while producing its reply."""

    tool_name: str
    arguments: dict
    ok: bool
    output: dict | None = Field(default=None, description="Present only when ok is true.")
    error_code: str | None = Field(default=None, description="Present only when ok is false.")
    error_message: str | None = Field(default=None, description="Present only when ok is false.")


class AgentChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
