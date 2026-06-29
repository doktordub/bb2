from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.orchestration.core import DefaultOrchestrationRuntime


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
    "APP_CONFIG_OVERRIDE_PATH",
    "APP_DATA_DIR",
    "APP_CONFIG_STRICT",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_RELOAD",
    "LOG_LEVEL",
    "LOG_JSON",
    "MCP_MAIN_URL",
    "LLM_LOCAL_QWEN_BASE_URL",
    "LLM_LOCAL_QWEN_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "MEMORY_STORE_CONFIG",
    "SQLITE_WORKFLOW_STATE_URL",
    "SQLITE_TRACE_URL",
]


def build_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/api_with_fake_mcp_tooling.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_startup_builds_real_tool_gateway(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app):
        container = app.state.container
        assert container is not None
        assert isinstance(container.session_service.orchestrator, DefaultOrchestrationRuntime)
        assert container.orchestrator is container.session_service.orchestrator
        assert container.tool_gateway is container.session_service.orchestrator.tools

        health = asyncio.run(container.tool_gateway.health())
        capabilities = asyncio.run(container.tool_gateway.capabilities())

    assert health.tooling_enabled is True
    assert health.mcp_configured is True
    assert health.mcp_status == "ok"
    assert health.tools_configured == 1
    assert health.tools_discovered == 1
    assert capabilities.enabled is True
    assert [tool.name for tool in capabilities.available_logical_tools] == ["documents.search"]