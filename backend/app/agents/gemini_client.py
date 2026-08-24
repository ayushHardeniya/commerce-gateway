"""Gemini client construction and schema translation.

This module owns building a configured Gemini client and translating our
provider-neutral `Tool` contract into Gemini's function-declaration format.
`app.agents.buyer` also imports `google.genai` directly (it drives the
conversation loop using Gemini's own `Content`/`Part`/`FunctionCall` types),
so this isn't the only file that knows about Gemini — but it is deliberately
Gemini-specific rather than a generic multi-provider abstraction: if another
provider is added later, it gets its own equivalent module rather than a
shared interface neither provider actually needs yet.
"""

from __future__ import annotations

from collections.abc import Iterable

from google import genai
from google.genai import types

from app.agents.tools.base import Tool
from app.core.config import Settings


class GeminiConfigurationError(Exception):
    """Raised when Gemini can't be used because it isn't configured."""


def build_client(settings: Settings) -> genai.Client:
    if not settings.gemini_api_key:
        raise GeminiConfigurationError(
            "GEMINI_API_KEY is not configured; the AI buyer is unavailable."
        )
    return genai.Client(api_key=settings.gemini_api_key)


def declare_tools(tools: Iterable[Tool]) -> list[types.Tool]:
    """Build the Gemini `tools` config from our own `Tool` objects.

    Each tool's Pydantic input schema is handed to Gemini verbatim as JSON
    Schema (`parameters_json_schema`) — there is exactly one schema Gemini
    ever sees for a tool, the same one `Tool.run` validates against.
    """
    declarations = [
        types.FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters_json_schema=tool.input_model.model_json_schema(),
        )
        for tool in tools
    ]
    return [types.Tool(function_declarations=declarations)]
