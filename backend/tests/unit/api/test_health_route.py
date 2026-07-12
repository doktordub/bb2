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


def test_health_route_returns_api_facing_shape_with_safe_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-health-1234"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["trace_id"] == "trace-health-1234"
    assert payload["service"] == "pluggable-agentic-ai-backend"
    assert payload["version"] == "0.1.0"
    assert payload["environment"] == "local"
    assert payload["backend"] == {
        "configured": True,
        "service": "pluggable-agentic-ai-backend",
        "version": "0.1.0",
        "environment": "local",
    }
    assert payload["api"] == {
        "configured": True,
        "docs_enabled": True,
        "streaming_enabled": False,
    }
    assert payload["visualization"] == {
        "status": "ok",
        "configured": True,
        "enabled": False,
        "default_renderer": "echarts",
        "supported_chart_types_count": 19,
        "context_summary_enabled": True,
        "artifact_store_enabled": False,
    }
    assert payload["workflow_state"]["provider"] == "sqlite"
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
    assert payload["mcp"] == {
        "status": "not_configured",
        "configured": True,
        "tooling_enabled": False,
        "adapter_reachable": False,
        "mcp_status": "disabled",
        "discovery_enabled": True,
        "discovery_state": "disabled",
        "tools_configured": 0,
        "tools_discovered": 0,
        "tools_enabled": 0,
        "registry_status": "disabled",
        "transport": "http",
        "server_name": "main",
        "identity_mode": "none",
    }
    assert payload["checks"]["visualization"] == payload["visualization"]
    assert payload["checks"]["workflow_state"] == payload["workflow_state"]
    assert payload["checks"]["trace"] == payload["trace"]