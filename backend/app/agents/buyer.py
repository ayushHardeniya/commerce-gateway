"""The AI buyer: a small, bounded Gemini tool-calling loop.

The safety boundary this module exists to enforce: Gemini only ever gets
the explicitly declared tools (`app.agents.tools.DEFAULT_TOOLS` by
default) — catalog discovery plus cart/checkout preparation. It cannot
reach pricing, policy, authorization, or payment execution, because no
tool for any of those exists yet; that is enforced by omission, not by a
runtime permission check that could be misconfigured. Every tool call
Gemini proposes is validated and executed through the existing `Tool`
contract (`app.agents.tools.base`), which in turn only ever calls
deterministic application/domain services (`app.catalog`,
`app.commerce.cart`, `app.commerce.checkout`) — never the database or a
repository directly, and never anything that computes a price or a total
itself.

The loop itself is intentionally not recursive or open-ended: it runs at
most `max_tool_iterations` model turns and then stops with a clear error,
rather than looping indefinitely on a model that never settles on a final
answer.
"""

from __future__ import annotations

import httpx
from google.genai import types
from google.genai.errors import APIError
from sqlalchemy.orm import Session

from app.agents.gemini_client import GeminiConfigurationError, build_client, declare_tools
from app.agents.schemas import AgentChatResponse, ToolCallRecord
from app.agents.tools import DEFAULT_TOOLS
from app.agents.tools.base import Tool
from app.core.config import Settings, get_settings

DEFAULT_MAX_TOOL_ITERATIONS = 4

# Sent with every request as `GenerateContentConfig.system_instruction` — the
# one guardrail this module adds against a real failure mode: the catalog
# only ever prices in USD, but a user may naturally state a budget in their
# own currency (e.g. INR). Nothing in this codebase performs currency
# conversion (no FX service, deliberately), so the model must never do it
# silently either: an approximate, LLM-guessed conversion presented as if it
# settled a budget question would be exactly the kind of unverified
# financial claim `CLAUDE.md`'s determinism boundary rules out. This
# instruction is the entire mechanism — there is no code-level currency
# check, because the mismatch only exists in the user's free-text message,
# which only the model reads.
CURRENCY_SAFETY_INSTRUCTION = (
    "Every price you see from a tool (search_catalog, get_product, and any cart or "
    "checkout total) is in USD — this catalog only sells in USD, never any other "
    "currency. If the user states a budget or amount in a different currency (for "
    "example INR, EUR, GBP, or symbols like ₹ or €), you have no access to a "
    "real exchange rate and this system provides none. Never convert the amount "
    "yourself, and never state or imply that their budget is satisfied, exceeded, or "
    "otherwise compared against a USD price using your own estimate of an exchange "
    "rate. Instead, tell the user plainly that prices here are in USD and ask them to "
    "restate their budget in USD before you compare it to anything."
)

# Transport-level failures the google-genai SDK's own retry logic (see
# google.genai._api_client) treats as transient and re-raises as-is once
# retries are exhausted, rather than wrapping in `APIError` — `APIError` only
# covers requests that actually received an HTTP response.
_TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.ConnectError)


class AgentError(Exception):
    """Base for agent-loop failures that must surface as a real API error
    rather than a fabricated success response."""


class AgentConfigurationError(AgentError):
    """Gemini isn't configured (no API key)."""


class AgentProviderError(AgentError):
    """Gemini's API returned no usable response, or the request to it failed."""


class AgentIterationLimitExceeded(AgentError):
    """The model didn't produce a final response within the iteration budget."""


class AIBuyerService:
    """One user message in, one grounded reply out.

    `client` is injectable so tests can drive the loop against a fake
    Gemini client rather than the real network/SDK; when omitted, a real
    `genai.Client` is built lazily from `settings` on first use, so
    constructing this service (and starting the app) never requires
    `GEMINI_API_KEY` to be set.
    """

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        tools: tuple[type[Tool], ...] = DEFAULT_TOOLS,
        max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
        client: object | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._max_tool_iterations = max_tool_iterations
        self._tools_by_name: dict[str, Tool] = {tool_cls.name: tool_cls(db) for tool_cls in tools}
        self._client = client

    def chat(self, message: str) -> AgentChatResponse:
        client = self._get_client()
        declared_tools = declare_tools(self._tools_by_name.values())
        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=message)])
        ]
        tool_calls: list[ToolCallRecord] = []

        for _ in range(self._max_tool_iterations):
            response = self._generate(client, contents, declared_tools)
            candidate = _first_candidate(response)
            function_calls = _function_call_parts(candidate)

            if not function_calls:
                return AgentChatResponse(reply=_final_text(candidate), tool_calls=tool_calls)

            contents.append(candidate.content)
            contents.append(
                types.Content(
                    role="user",
                    parts=[self._execute_tool_call(call, tool_calls) for call in function_calls],
                )
            )

        raise AgentIterationLimitExceeded(
            f"The agent did not produce a final response within "
            f"{self._max_tool_iterations} model turn(s)."
        )

    def _get_client(self) -> object:
        if self._client is None:
            try:
                self._client = build_client(self._settings)
            except GeminiConfigurationError as exc:
                raise AgentConfigurationError(str(exc)) from exc
        return self._client

    def _generate(
        self, client: object, contents: list[types.Content], tools: list[types.Tool]
    ) -> types.GenerateContentResponse:
        try:
            return client.models.generate_content(
                model=self._settings.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=tools, system_instruction=CURRENCY_SAFETY_INSTRUCTION
                ),
            )
        except (APIError, *_TRANSPORT_ERRORS) as exc:
            raise AgentProviderError(f"Gemini request failed: {exc}") from exc

    def _execute_tool_call(
        self, call: types.FunctionCall, tool_calls: list[ToolCallRecord]
    ) -> types.Part:
        arguments = dict(call.args or {})
        tool = self._tools_by_name.get(call.name)

        if tool is None:
            record = ToolCallRecord(
                tool_name=call.name or "<missing>",
                arguments=arguments,
                ok=False,
                error_code="unknown_tool",
                error_message=f"'{call.name}' is not an available tool.",
            )
            response_payload = {
                "error": {"code": record.error_code, "message": record.error_message}
            }
        else:
            result = tool.run(arguments)
            if result.ok:
                output = result.output.model_dump(mode="json")
                record = ToolCallRecord(
                    tool_name=call.name, arguments=arguments, ok=True, output=output
                )
                response_payload = {"result": output}
            else:
                record = ToolCallRecord(
                    tool_name=call.name,
                    arguments=arguments,
                    ok=False,
                    error_code=result.error.code.value,
                    error_message=result.error.message,
                )
                response_payload = {
                    "error": {"code": record.error_code, "message": record.error_message}
                }

        tool_calls.append(record)
        return types.Part(
            function_response=types.FunctionResponse(
                id=call.id, name=call.name, response=response_payload
            )
        )


def _first_candidate(response: types.GenerateContentResponse) -> types.Candidate:
    if not response.candidates:
        raise AgentProviderError("Gemini returned no candidates for this request.")
    return response.candidates[0]


def _function_call_parts(candidate: types.Candidate) -> list[types.FunctionCall]:
    if candidate.content is None or not candidate.content.parts:
        return []
    return [part.function_call for part in candidate.content.parts if part.function_call]


def _final_text(candidate: types.Candidate) -> str:
    if candidate.content is not None and candidate.content.parts:
        text = "".join(part.text for part in candidate.content.parts if part.text)
        if text.strip():
            return text
    raise AgentProviderError(
        f"Gemini did not return a usable response (finish_reason={candidate.finish_reason})."
    )
