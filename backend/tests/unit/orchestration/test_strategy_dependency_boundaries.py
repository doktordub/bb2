from __future__ import annotations

import ast
from pathlib import Path


STRATEGY_DIR = Path(__file__).resolve().parents[3] / "app" / "orchestration" / "strategies"
FORBIDDEN_IMPORT_PREFIXES = (
    "app.api",
    "app.session",
    "app.persistence.sqlite",
    "app.persistence.sqlite_workflow_state_store",
    "app.persistence.sqlite_trace_store",
    "app.tools.mcp",
    "sqlite3",
    "aiosqlite",
    "memory_store",
    "mcp",
    "openai",
    "google",
)


def test_strategy_modules_do_not_import_forbidden_infrastructure_dependencies() -> None:
    violations: dict[str, list[str]] = {}

    for path in sorted(STRATEGY_DIR.glob("*.py")):
        imports = sorted({module for module in _read_imports(path) if _is_forbidden(module)})
        if imports:
            violations[path.name] = imports

    assert violations == {}


def _read_imports(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_PREFIXES)