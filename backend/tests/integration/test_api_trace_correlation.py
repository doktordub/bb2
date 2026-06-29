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
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/api_with_real_sqlite_stores.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_trace_id_is_returned_and_recorded_in_trace_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    trace_database_path = tmp_path / "trace.db"

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-trace-id": "trace-correlation-0001"},
            json={"message": "correlate this", "session_id": "session_trace_123"},
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-correlation-0001"
    assert response.json()["trace_id"] == "trace-correlation-0001"

    with sqlite3.connect(trace_database_path) as connection:
        rows = connection.execute(
            "SELECT event_name FROM trace_events WHERE trace_id = ? ORDER BY sequence_no ASC",
            ("trace-correlation-0001",),
        ).fetchall()

    event_names = {row[0] for row in rows}
    assert "request_received" in event_names
    assert "workflow_state_loaded" in event_names
    assert "workflow_state_saved" in event_names
    assert "session_created" in event_names
    assert "response_returned" in event_names