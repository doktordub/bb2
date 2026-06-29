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


def test_startup_builds_real_llm_gateway(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))

    with TestClient(app):
        container = app.state.container
        assert container is not None
        assert isinstance(container.session_service, object)
        assert isinstance(container.session_service.orchestrator, DefaultOrchestrationRuntime)
        assert container.orchestrator is container.session_service.orchestrator

        health = asyncio.run(container.llm_gateway.health())
        profiles = asyncio.run(container.llm_gateway.list_profiles())

    assert health.default_profile == "local_reasoning"
    assert health.providers["local_provider"].type == "openai_compatible"
    assert health.providers["local_provider"].status == "ok"
    assert [profile.name for profile in profiles] == ["local_reasoning"]