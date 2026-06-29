from __future__ import annotations

import json
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


def test_reset_clears_workflow_state_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    workflow_database_path = tmp_path / "workflow_state.db"
    trace_database_path = tmp_path / "trace.db"

    with TestClient(app) as client:
        chat = client.post(
            "/chat",
            headers={"x-trace-id": "trace-reset-chat-0001"},
            json={"message": "reset me", "session_id": "session_reset_123"},
        )
        reset = client.post(
            "/sessions/session_reset_123/reset",
            headers={"x-trace-id": "trace-reset-op-0001"},
            json={"reason": "user_requested"},
        )

    assert chat.status_code == 200
    assert reset.status_code == 200
    assert reset.headers["x-trace-id"] == "trace-reset-op-0001"
    assert reset.headers["x-session-id"] == "session_reset_123"

    with sqlite3.connect(workflow_database_path) as connection:
        current_row = connection.execute(
            """
            SELECT message_count, current_step, state_json
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session_reset_123",),
        ).fetchone()
        reset_count = connection.execute(
            "SELECT COUNT(*) FROM workflow_state_resets WHERE session_id = ?",
            ("session_reset_123",),
        ).fetchone()[0]

    assert current_row is not None
    assert current_row[0] == 0
    assert current_row[1] is None
    assert reset_count == 1

    reset_state = json.loads(current_row[2])
    assert reset_state["conversation"]["messages"] == []
    assert reset_state["metadata"]["loaded_empty"] is True

    with sqlite3.connect(trace_database_path) as connection:
        trace_count = connection.execute(
            "SELECT COUNT(*) FROM trace_events WHERE trace_id IN (?, ?)",
            ("trace-reset-chat-0001", "trace-reset-op-0001"),
        ).fetchone()[0]

    assert trace_count > 0