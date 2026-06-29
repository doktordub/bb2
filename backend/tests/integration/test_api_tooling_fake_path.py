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
        "tests/fixtures/config/api_with_fake_mcp_tooling.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_chat_route_executes_fake_tool_path_through_orchestration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    trace_database_path = tmp_path / "trace.db"

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-trace-id": "trace-tooling-chat-0001"},
            json={
                "message": "tool: backend architecture",
                "session_id": "session_tooling_1",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-tooling-chat-0001"
    assert response.headers["x-session-id"] == "session_tooling_1"

    payload = response.json()
    assert payload["data"]["answer"] == "fake response"
    assert payload["data"]["agent_name"] == "support_agent"
    assert payload["data"]["strategy_name"] == "tool_assisted"
    assert payload["data"]["llm_profile"] == "fake_basic"
    assert payload["data"]["memory_updates"] == []
    assert payload["data"]["tool_calls"][0]["tool_name"] == "documents.search"
    assert payload["data"]["tool_calls"][0]["status"] == "completed"
    assert payload["metadata"] == {
        "usecase": "default_chat",
        "message_count": 2,
        "message_count_before": 0,
    }

    with sqlite3.connect(trace_database_path) as connection:
        rows = connection.execute(
            """
            SELECT event_name, payload_json
            FROM trace_events
            WHERE trace_id = ?
            ORDER BY sequence_no ASC
            """,
            ("trace-tooling-chat-0001",),
        ).fetchall()

    event_names = [row[0] for row in rows]
    assert "tool_call_started" in event_names
    assert "tool_call_completed" in event_names

    completed_payload = next(
        json.loads(row[1])
        for row in rows
        if row[0] == "tool_call_completed"
    )
    assert completed_payload == {}