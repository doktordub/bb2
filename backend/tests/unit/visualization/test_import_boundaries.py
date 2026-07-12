from __future__ import annotations

import ast
from pathlib import Path


VISUALIZATION_ROOT = Path("app/visualization")
FORBIDDEN_IMPORT_PREFIXES = {
    "frontend": "frontend code",
    "app.tools.mcp": "MCP client runtime",
    "sqlite3": "SQLite",
    "pyarcadedb": "ArcadeDB client",
    "arcadedb": "ArcadeDB client",
    "openai": "provider SDK",
    "anthropic": "provider SDK",
    "google.generativeai": "provider SDK",
    "google.genai": "provider SDK",
    "httpx": "external API client",
    "aiohttp": "external API client",
    "requests": "external API client",
}


def test_visualization_package_does_not_import_forbidden_runtime_dependencies() -> None:
    violations: list[str] = []

    for file_path in sorted(VISUALIZATION_ROOT.rglob("*.py")):
        if "__pycache__" in file_path.parts:
            continue
        module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for line_number, import_name in _iter_import_names(module):
            forbidden = _matching_forbidden_prefix(import_name)
            if forbidden is None:
                continue
            violations.append(
                f"{file_path.as_posix()}:{line_number} imports {import_name!r} ({forbidden})"
            )

    assert violations == []


def _iter_import_names(module: ast.AST) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imports.append((node.lineno, node.module))
    return imports


def _matching_forbidden_prefix(import_name: str) -> str | None:
    for prefix, label in FORBIDDEN_IMPORT_PREFIXES.items():
        if import_name == prefix or import_name.startswith(f"{prefix}."):
            return label
    return None