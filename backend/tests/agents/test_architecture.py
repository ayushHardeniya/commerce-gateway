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
