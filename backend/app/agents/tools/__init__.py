"""Tools available to the AI buyer.

A tool is the only channel through which the (not yet built) agent loop can
read or affect catalog state: the LLM proposes a call by name with JSON
input, this layer validates it against a typed schema and executes it
deterministically, and returns a typed, structured `ToolResult` — never a
raw exception, a database handle, or free-form code execution.

`CATALOG_TOOLS` is a plain tuple, not a plugin registry: adding a tool means
implementing a `Tool` subclass and listing it here, nothing more.
"""

from app.agents.tools.base import Tool, ToolError, ToolErrorCode, ToolResult
from app.agents.tools.catalog import GetProductTool, SearchCatalogTool

CATALOG_TOOLS: tuple[type[Tool], ...] = (SearchCatalogTool, GetProductTool)

__all__ = [
    "CATALOG_TOOLS",
    "GetProductTool",
    "SearchCatalogTool",
    "Tool",
    "ToolError",
    "ToolErrorCode",
    "ToolResult",
]
