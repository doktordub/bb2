from __future__ import annotations

import ast
from pathlib import Path


REPORTING_ROOT = Path(__file__).resolve().parents[2] / "tools" / "reporting"


def test_reporting_plugin_modules_do_not_import_backend_or_frontend_packages() -> None:
    python_files = sorted(path for path in REPORTING_ROOT.glob("*.py") if path.name != "__init__.py")
    violations: list[str] = []

    for path in python_files:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name in {"backend", "frontend"}:
                        violations.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                root_name = node.module.split(".", 1)[0]
                if root_name in {"backend", "frontend"}:
                    violations.append(f"{path.name}: from {node.module} import ...")

    assert violations == []