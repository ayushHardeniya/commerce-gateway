"""Structural checks for the agents<->catalog dependency direction.

`app.agents` may import from `app.catalog`, never the reverse. This is
checked statically (parsing imports) rather than by importing modules and
inspecting `sys.modules`, so it fails on a stray import even if nothing else
in the test suite happens to exercise it.
"""

import ast
import importlib
from pathlib import Path


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_catalog_module_does_not_import_agents() -> None:
    catalog_dir = Path(importlib.import_module("app.catalog").__file__).parent

    for path in catalog_dir.glob("*.py"):
        imported = _imported_top_level_modules(path)
        offending = {name for name in imported if name.startswith("app.agents")}
        assert not offending, f"{path} must not import from app.agents: {offending}"


def test_commerce_module_does_not_import_agents() -> None:
    commerce_dir = Path(importlib.import_module("app.commerce").__file__).parent

    for path in commerce_dir.rglob("*.py"):
        imported = _imported_top_level_modules(path)
        offending = {name for name in imported if name.startswith("app.agents")}
        assert not offending, f"{path} must not import from app.agents: {offending}"


def test_agents_tools_only_depend_on_catalog_and_shared_infrastructure() -> None:
    agents_dir = Path(importlib.import_module("app.agents").__file__).parent
    allowed_prefixes = ("app.agents", "app.catalog", "app.commerce", "app.db", "app.core")

    for path in agents_dir.rglob("*.py"):
        imported = _imported_top_level_modules(path)
        app_imports = {name for name in imported if name.startswith("app.")}
        offending = {name for name in app_imports if not name.startswith(allowed_prefixes)}
        assert not offending, f"{path} has an unexpected app-internal dependency: {offending}"


def test_no_payment_tool_is_declared() -> None:
    """The AI buyer must never gain the ability to initiate, confirm,
    capture, authorize, or refund a payment — enforced by omission (no such
    `Tool` exists), the same pattern already used for `authorize_checkout`
    (see `docs/decisions/0004-agent-tool-contract.md`). This is a regression
    test: it fails the moment anyone adds a payment tool, on purpose or by
    accident, rather than relying on code review alone."""
    from app.agents.tools import DEFAULT_TOOLS

    forbidden_substrings = ("payment", "pay", "razorpay", "charge", "capture", "refund")
    offending = [
        tool_cls.name
        for tool_cls in DEFAULT_TOOLS
        if any(word in tool_cls.name.lower() for word in forbidden_substrings)
    ]
    assert not offending, f"Payment-shaped tool(s) exposed to the agent: {offending}"


def test_payment_module_does_not_import_agents() -> None:
    payment_dir = Path(importlib.import_module("app.commerce.payment").__file__).parent

    for path in payment_dir.glob("*.py"):
        imported = _imported_top_level_modules(path)
        offending = {name for name in imported if name.startswith("app.agents")}
        assert not offending, f"{path} must not import from app.agents: {offending}"


def test_no_transaction_tool_is_declared() -> None:
    """The AI buyer must never gain the ability to create or transition a
    `Transaction` directly — enforced by omission (no such `Tool` exists),
    the same pattern `test_no_payment_tool_is_declared` already uses. State
    transitions stay deterministic application code, reachable only through
    `app.commerce.transaction.router` (HTTP)."""
    from app.agents.tools import DEFAULT_TOOLS

    forbidden_substrings = ("transaction", "transition")
    offending = [
        tool_cls.name
        for tool_cls in DEFAULT_TOOLS
        if any(word in tool_cls.name.lower() for word in forbidden_substrings)
    ]
    assert not offending, f"Transaction-shaped tool(s) exposed to the agent: {offending}"


def test_transaction_module_does_not_import_agents() -> None:
    transaction_dir = Path(importlib.import_module("app.commerce.transaction").__file__).parent

    for path in transaction_dir.glob("*.py"):
        imported = _imported_top_level_modules(path)
        offending = {name for name in imported if name.startswith("app.agents")}
        assert not offending, f"{path} must not import from app.agents: {offending}"
