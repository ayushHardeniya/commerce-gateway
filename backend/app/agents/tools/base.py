"""Provider-neutral contract for tools an AI buyer can call.

A tool is the only channel through which an LLM can read or affect
application state. It never gets direct database access, raw SQL, arbitrary
HTTP access, or code execution — it can only invoke a `Tool` by name with a
JSON-shaped input, which this layer validates against a typed schema and
executes deterministically. The result is always a structured `ToolResult`:
`run()` never raises, so a future agent loop never needs exception handling
to interpret what a tool call did.

Nothing here references a specific LLM vendor or SDK — that adapter is a
later, separate piece of work built on top of this contract.
"""

from __future__ import annotations

import abc
from enum import StrEnum

from pydantic import BaseModel, ValidationError


class ToolErrorCode(StrEnum):
    """Closed set of ways a tool call can fail, so a caller can branch on
    `code` rather than parsing `message` text."""

    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INTERNAL_ERROR = "internal_error"


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str


class ToolResult[OutputT: BaseModel](BaseModel):
    """The outcome of a tool call: exactly one of `output`/`error` is set."""

    output: OutputT | None = None
    error: ToolError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, output: OutputT) -> ToolResult[OutputT]:
        return cls(output=output)

    @classmethod
    def failure(cls, code: ToolErrorCode, message: str) -> ToolResult[OutputT]:
        return cls(error=ToolError(code=code, message=message))


class ToolNotFoundError(Exception):
    """Raise from `Tool._execute` to signal a structured not-found result."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ToolConflictError(Exception):
    """Raise from `Tool._execute` when the request is well-formed and its
    target exists, but current state blocks it (e.g. an out-of-stock
    product, a price that changed, an already-active checkout)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Tool[InputT: BaseModel, OutputT: BaseModel](abc.ABC):
    """Base class for a single agent-callable operation.

    Subclasses set `name`, `description`, `input_model`, `output_model` and
    implement `_execute`. Everything else (validation, structured error
    conversion) is handled once here so every tool behaves the same way.
    """

    name: str
    description: str
    input_model: type[InputT]
    output_model: type[OutputT]

    def run(self, raw_input: dict) -> ToolResult[OutputT]:
        try:
            parsed_input = self.input_model.model_validate(raw_input)
        except ValidationError as exc:
            return ToolResult.failure(ToolErrorCode.INVALID_INPUT, _describe(exc))

        try:
            output = self._execute(parsed_input)
        except ToolNotFoundError as exc:
            return ToolResult.failure(ToolErrorCode.NOT_FOUND, exc.message)
        except ToolConflictError as exc:
            return ToolResult.failure(ToolErrorCode.CONFLICT, exc.message)
        except Exception:
            # Deliberately generic: a database/programming error must never
            # reach the LLM as a stack trace or raw driver message.
            return ToolResult.failure(
                ToolErrorCode.INTERNAL_ERROR,
                f"An internal error occurred while running the '{self.name}' tool.",
            )

        return ToolResult.success(output)

    @abc.abstractmethod
    def _execute(self, input: InputT) -> OutputT:
        """Deterministic execution against already-validated input.

        Must not call an LLM, use randomness, or otherwise depend on
        anything but the current catalog state and `input` — the same
        (state, input) pair must always produce the same output.
        """


def _describe(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        loc = ".".join(str(segment) for segment in error["loc"])
        parts.append(f"{loc}: {error['msg']}" if loc else error["msg"])
    return "; ".join(parts)
