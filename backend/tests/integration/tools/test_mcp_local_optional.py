from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.tools.factory import build_tooling_runtime


@pytest.mark.skipif(
    os.getenv("BB2_RUN_LOCAL_MCP_TESTS") != "1",
    reason="Local MCP smoke tests are opt-in.",
)
async def test_local_mcp_optional_smoke() -> None:
    config = load_validated_config(Path("tests/fixtures/config/tooling_local_mcp_optional.yaml"))
    runtime = build_tooling_runtime(config)

    health = await runtime.mcp_adapter.health()

    assert health.status == "ok"

    tools = await runtime.mcp_adapter.list_tools()

    assert isinstance(tools, list)