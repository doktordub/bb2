from __future__ import annotations

import sqlite3

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


def test_trace_payload_policy_keeps_trace_payloads_summary_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    trace_database_path = tmp_path / "trace.db"

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-policy-health-0001"})

    assert response.status_code == 200
    with sqlite3.connect(trace_database_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM trace_events WHERE trace_id = ? ORDER BY created_at DESC, trace_id DESC, sequence_no DESC LIMIT 1",
            ("trace-policy-health-0001",),
        ).fetchone()

    assert row is not None
    payload_json = row[0]
    assert isinstance(payload_json, str)
    assert "stack_trace" not in payload_json
    assert "Bearer " not in payload_json