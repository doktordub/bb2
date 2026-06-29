from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


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
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_health_route_reports_real_store_statuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-health-int-0001"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["trace_id"] == "trace-health-int-0001"
    assert payload["workflow_state"]["status"] == "ok"
    assert payload["workflow_state"]["provider"] == "sqlite"
    assert payload["trace"]["status"] == "ok"
    assert payload["trace"]["provider"] == "sqlite"
    assert payload["llm"] == {
        "status": "ok",
        "providers_configured": True,
        "profiles_configured": True,
        "default_profile": "local_reasoning",
        "providers": {
            "local_provider": {
                "status": "ok",
                "type": "openai_compatible",
                "enabled": True,
            }
        },
        "profiles": {
            "local_reasoning": {
                "status": "ok",
                "provider": "local_provider",
                "enabled": True,
                "supports_streaming": True,
            }
        },
    }
    assert payload["checks"]["persistence"]["components"] == {
        "workflow_state": "ok",
        "trace": "ok",
    }
    assert payload["memory"]["status"] == "ok"
    assert payload["memory"]["provider"] == "memory_store"