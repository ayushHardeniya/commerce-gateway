"""M8A: regression coverage for `Tool.run()`'s own safety net.

Every existing tool test exercises `NOT_FOUND`/`INVALID_INPUT`/`CONFLICT` —
all raised deliberately from a tool's `_execute`. None of them prove the
thing `run()`'s docstring actually promises: that `run()` never raises at
all, even when `_execute` fails in a way nobody anticipated (a bug, a
dropped connection, anything not already modeled as `ToolNotFoundError`/
`ToolConflictError`). That fallback is what stands between a backend defect
and a raw exception reaching the agent loop.
"""

from pydantic import BaseModel

from app.agents.tools.base import Tool, ToolErrorCode


class _Input(BaseModel):
    pass


class _Output(BaseModel):
    ok: bool = True


class _ExplodingTool(Tool[_Input, _Output]):
    """A test-only tool whose `_execute` fails in a way no tool's real
    `_execute` is expected to — not a `ToolNotFoundError`/`ToolConflictError`,
    just an ordinary bug-shaped exception."""

    name = "exploding_tool"
    description = "Test-only tool that raises an unexpected exception."
    input_model = _Input
    output_model = _Output

    def _execute(self, input: _Input) -> _Output:
        raise RuntimeError("simulated unexpected failure, e.g. a dropped DB connection")


def test_run_converts_an_unexpected_exception_to_a_structured_internal_error() -> None:
    tool = _ExplodingTool()

    result = tool.run({})

    assert result.ok is False
    assert result.output is None
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INTERNAL_ERROR
    # Generic on purpose — never the raw exception message/type, which could
    # leak implementation detail (a driver error, a stack trace) to the LLM.
    assert "internal error" in result.error.message.lower()
    assert "exploding_tool" in result.error.message
    assert "RuntimeError" not in result.error.message
    assert "dropped DB connection" not in result.error.message
