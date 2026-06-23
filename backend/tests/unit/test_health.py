from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
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


def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_health_route(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MCP_MAIN_URL", "https://mcp.example.local")
    monkeypatch.setenv("OPENAI_API_KEY", "top-secret-openai-key")
    monkeypatch.setenv("MEMORY_STORE_CONFIG", "../config/memory_store.yaml")
    monkeypatch.setenv(
        "SQLITE_WORKFLOW_STATE_URL",
        "sqlite+aiosqlite:///./data/workflow_state.db",
    )
    monkeypatch.setenv("SQLITE_TRACE_URL", "sqlite+aiosqlite:///./data/trace.db")

    app = create_app(load_settings(env_file=None))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    UUID(response.headers["x-trace-id"])

    assert response.json() == {
        "status": "ok",
        "service": "pluggable-agentic-ai-backend",
        "version": "0.1.0",
        "environment": "test",
        "checks": {
            "settings": {"status": "ok"},
            "config": {"status": "not_configured", "configured": False},
            "logging": {"status": "ok"},
            "mcp": {"status": "not_checked", "configured": True},
            "llm": {"status": "not_checked", "configured": True},
            "memory": {"status": "not_checked", "configured": True},
            "workflow_state": {"status": "not_checked", "configured": True},
            "trace": {"status": "not_checked", "configured": True},
        },
    }

    response_body = response.text
    assert "https://mcp.example.local" not in response_body
    assert "top-secret-openai-key" not in response_body
    assert "sqlite+aiosqlite:///./data/workflow_state.db" not in response_body
    assert "sqlite+aiosqlite:///./data/trace.db" not in response_body
