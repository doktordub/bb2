from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.session.service import DefaultSessionService


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
        "tests/fixtures/config/api_with_real_sqlite_stores_fake_llm.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_chat_route_persists_real_workflow_state_through_default_session_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    workflow_database_path = tmp_path / "workflow_state.db"

    with TestClient(app) as client:
        assert isinstance(app.state.container.session_service, DefaultSessionService)

        first = client.post(
            "/chat",
            headers={"x-trace-id": "trace-walk-0001"},
            json={"message": "hello default session service", "session_id": "session_walk_123"},
        )
        second = client.post(
            "/chat",
            headers={"x-trace-id": "trace-walk-0002"},
            json={"message": "second turn", "session_id": "session_walk_123"},
        )

    assert first.status_code == 200
    assert first.headers["x-trace-id"] == "trace-walk-0001"
    assert first.headers["x-session-id"] == "session_walk_123"
    assert first.json()["data"]["answer"] == "fake response"
    assert first.json()["metadata"] == {
        "usecase": "default_chat",
        "message_count": 2,
        "message_count_before": 0,
    }

    assert second.status_code == 200
    assert second.headers["x-trace-id"] == "trace-walk-0002"
    assert second.headers["x-session-id"] == "session_walk_123"
    assert second.json()["data"]["answer"] == "fake response"
    assert second.json()["metadata"] == {
        "usecase": "default_chat",
        "message_count": 4,
        "message_count_before": 2,
    }

    with sqlite3.connect(workflow_database_path) as connection:
        row = connection.execute(
            """
            SELECT state_version, message_count, current_step, state_json
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session_walk_123",),
        ).fetchone()

    assert row is not None
    assert row[0] == 2
    assert row[1] == 4
    assert row[2] == "answered"

    state = json.loads(row[3])
    messages = state["conversation"]["messages"]
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello default session service"
    assert isinstance(messages[0].get("created_at"), str)
    assert messages[0]["metadata"] == {
        "transport": "request/response",
        "usecase": "default_chat",
        "request_id": "trace-walk-0001",
        "turn_id": "trace-walk-0001",
        "trace_id": "trace-walk-0001",
    }
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "fake response"
    assert isinstance(messages[1].get("created_at"), str)
    assert messages[1]["metadata"] == {
        "agent_name": "support_agent",
        "strategy_name": "direct_agent",
        "llm_profile": "fake_basic",
        "request_id": "trace-walk-0001",
        "turn_id": "trace-walk-0001",
        "trace_id": "trace-walk-0001",
        "transport": "request/response",
        "usecase": "default_chat",
    }
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "second turn"
    assert isinstance(messages[2].get("created_at"), str)
    assert messages[2]["metadata"] == {
        "transport": "request/response",
        "usecase": "default_chat",
        "request_id": "trace-walk-0002",
        "turn_id": "trace-walk-0002",
        "trace_id": "trace-walk-0002",
    }
    assert messages[3]["role"] == "assistant"
    assert messages[3]["content"] == "fake response"
    assert isinstance(messages[3].get("created_at"), str)
    assert messages[3]["metadata"] == {
        "agent_name": "support_agent",
        "strategy_name": "direct_agent",
        "llm_profile": "fake_basic",
        "request_id": "trace-walk-0002",
        "turn_id": "trace-walk-0002",
        "trace_id": "trace-walk-0002",
        "transport": "request/response",
        "usecase": "default_chat",
    }
    assert state["last_result"] == {
        "agent_name": "support_agent",
        "strategy_name": "direct_agent",
        "llm_profile": "fake_basic",
    }
    assert state["metadata"]["trace_id"] == "trace-walk-0002"
    assert state["metadata"]["request_id"] == "trace-walk-0002"
    assert state["metadata"]["usecase"] == "default_chat"