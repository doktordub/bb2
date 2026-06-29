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


def test_startup_wires_orchestration_into_health_and_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        container = app.state.container
        assert container is not None
        assert isinstance(container.orchestrator, DefaultOrchestrationRuntime)
        assert container.orchestrator is container.session_service.orchestrator

        orchestration_health = asyncio.run(container.orchestrator.health())
        orchestration_capabilities = asyncio.run(container.orchestrator.capabilities())

        health_response = client.get("/health")
        capabilities_response = client.get("/capabilities")

    health_payload = health_response.json()
    assert health_response.status_code == 200
    assert health_payload["orchestration"]["status"] == orchestration_health.status
    assert health_payload["orchestration"]["default_strategy"] == orchestration_health.default_strategy
    assert health_payload["checks"]["orchestration"]["registered_strategy_count"] == orchestration_health.registered_strategy_count
    assert health_payload["checks"]["orchestration"]["strategy_types"] == ["direct_agent", "router"]

    capability_payload = capabilities_response.json()
    assert capabilities_response.status_code == 200
    assert [item["name"] for item in capability_payload["data"]["usecases"]] == [
        item.name for item in orchestration_capabilities.usecases
    ]
    assert [item["strategy_type"] for item in capability_payload["data"]["usecases"]] == [
        item.strategy_type for item in orchestration_capabilities.usecases
    ]