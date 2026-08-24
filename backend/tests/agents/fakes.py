"""A fake Gemini client for deterministic tests.

Builds real `google.genai.types` response objects (so parsing logic in
`app.agents.buyer` is exercised against the SDK's actual shapes) but never
makes a network call — `FakeGeminiClient.models.generate_content` just pops
the next canned response off a queue. A queued item may also be an
`Exception` instance, in which case it's raised instead of returned, to
simulate an `APIError` or a transport-level failure from the real SDK.
"""

from google.genai import types

_QueuedResult = types.GenerateContentResponse | Exception


class _FakeModels:
    def __init__(self, responses: list[_QueuedResult]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(
        self, *, model: str, contents: list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        if not self._responses:
            raise AssertionError("FakeGeminiClient ran out of canned responses")
        next_result = self._responses.pop(0)
        if isinstance(next_result, Exception):
            raise next_result
        return next_result


class FakeGeminiClient:
    def __init__(self, responses: list[_QueuedResult]) -> None:
        self.models = _FakeModels(responses)


def function_call_response(
    name: str, args: dict, *, call_id: str = "call-1"
) -> types.GenerateContentResponse:
    function_call = types.FunctionCall(id=call_id, name=name, args=args)
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model", parts=[types.Part(function_call=function_call)]
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


def parallel_function_call_response(
    calls: list[tuple[str, dict]],
) -> types.GenerateContentResponse:
    parts = [
        types.Part(function_call=types.FunctionCall(id=f"call-{i}", name=name, args=args))
        for i, (name, args) in enumerate(calls)
    ]
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


def text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


def empty_response() -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[])


def blocked_response(
    finish_reason: types.FinishReason = types.FinishReason.SAFETY,
) -> types.GenerateContentResponse:
    """A candidate with no function call and no usable text — e.g. a safety
    block or a malformed function call the API couldn't parse."""
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=None, finish_reason=finish_reason)]
    )
