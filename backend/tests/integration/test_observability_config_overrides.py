from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.persistence.trace_store import resolve_trace_store_path


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


def build_app_with_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    override_name: str,
):
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        f"tests/fixtures/config/{override_name}",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    return create_app(load_settings(env_file=None))


def test_observability_enabled_override_records_request_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app_with_override(monkeypatch, tmp_path, "observability_enabled.yaml")

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-enabled-123"})

        assert response.status_code == 200

        database_path = resolve_trace_store_path(app.state.container.config)
        with sqlite3.connect(database_path) as connection:
            payload_json = connection.execute(
                "SELECT payload_json FROM trace_events WHERE event_name = 'request_received' ORDER BY created_at DESC, trace_id DESC, sequence_no DESC LIMIT 1"
            ).fetchone()[0]

    assert json.loads(payload_json) == {
        "method": "GET",
        "route_template": "/health",
        "streaming": False,
    }


def test_trace_payloads_disabled_override_omits_request_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app_with_override(
        monkeypatch,
        tmp_path,
        "observability_trace_payloads_disabled.yaml",
    )

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-disabled-123"})

        assert response.status_code == 200

        database_path = resolve_trace_store_path(app.state.container.config)
        with sqlite3.connect(database_path) as connection:
            payload_json = connection.execute(
                "SELECT payload_json FROM trace_events WHERE event_name = 'request_received' ORDER BY created_at DESC, trace_id DESC, sequence_no DESC LIMIT 1"
            ).fetchone()[0]

    assert json.loads(payload_json) == {}


def test_health_minimal_override_hides_component_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app_with_override(monkeypatch, tmp_path, "health_minimal.yaml")

    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert app.state.container.config_summary == {"configured": True}

    checks = response.json()["checks"]
    assert all(set(component) == {"status"} for component in checks.values())


def test_health_detailed_override_exposes_safe_component_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app_with_override(monkeypatch, tmp_path, "health_detailed.yaml")

    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert app.state.container.config_summary == {
            "configured": True,
            "environment": "local",
            "active_usecase": "default_chat",
            "llm_profiles_count": 1,
            "mcp_configured": True,
            "llm_providers": ["local_provider"],
            "workflow_state_provider": "sqlite",
            "trace_provider": "sqlite",
            "memory_provider": "memory_store",
        }

    checks = response.json()["checks"]
    assert checks["config"] == {
        "status": "ok",
        "configured": True,
        "environment": "local",
        "active_usecase": "default_chat",
        "llm_profiles_count": 1,
        "mcp_configured": True,
        "llm_providers": ["local_provider"],
        "workflow_state_provider": "sqlite",
        "trace_provider": "sqlite",
        "memory_provider": "memory_store",
    }
    assert checks["observability"] == {
        "status": "ok",
        "trace_enabled": True,
        "trace_payloads_enabled": False,
        "trace_store_required": True,
        "structured_logging": True,
        "metrics_enabled": True,
        "trace_store_configured": True,
    }