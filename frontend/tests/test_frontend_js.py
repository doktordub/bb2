from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
JS_TEST_FILES = sorted(
    path.relative_to(FRONTEND_ROOT).as_posix()
    for path in (FRONTEND_ROOT / "tests" / "js").glob("*.test.mjs")
)


def test_frontend_javascript_modules() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend JavaScript module tests.")

    completed = subprocess.run(
        [node, "--test", *JS_TEST_FILES],
        cwd=FRONTEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        pytest.fail(
            "Node.js module tests failed.\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )