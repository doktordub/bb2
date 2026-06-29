from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.memory.gateway import DefaultMemoryGateway


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


def clear_settings_env(monkeypatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_startup_builds_memory_outside_persistence_and_reports_readiness(
    monkeypatch,
    tmp_path,
) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "tests/fixtures/config/memory_fake_basic.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        container = app.state.container

        assert isinstance(container.memory, DefaultMemoryGateway)
        assert not hasattr(container.persistence, "memory")
        assert container.memory is container.session_service.orchestrator.memory

        memory_health = asyncio.run(container.memory.health())
        assert memory_health["provider"] == "fake"
        assert memory_health["search_available"] is True
        assert memory_health["ingest_available"] is True

        health_response = client.get("/health")
        capabilities_response = client.get("/capabilities")

    assert health_response.status_code == 200
    assert health_response.json()["memory"]["provider"] == "fake"
    assert health_response.json()["checks"]["persistence"]["components"] == {
        "workflow_state": "ok",
        "trace": "ok",
    }

    assert capabilities_response.status_code == 200
    assert capabilities_response.json()["data"]["memory"] == {
        "enabled": True,
        "configured": True,
        "provider": "fake",
        "search_available": True,
        "ingest_available": True,
    }
