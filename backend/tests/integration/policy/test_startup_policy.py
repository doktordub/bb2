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


def test_startup_wires_policy_into_health_and_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        health_response = client.get("/health")
        capabilities_response = client.get("/capabilities")

    assert health_response.status_code == 200
    policy_health = health_response.json()["checks"]["policy"]
    assert policy_health["status"] == "ok"
    assert policy_health["configured"] is True
    assert policy_health["healthy"] is True
    assert policy_health["enabled"] is True
    assert policy_health["mode"] == "enforce"
    assert policy_health["profile_count"] == 1
    assert policy_health["rule_count"] == 12
    assert capabilities_response.status_code == 200
    assert "policy" not in capabilities_response.json()["data"]