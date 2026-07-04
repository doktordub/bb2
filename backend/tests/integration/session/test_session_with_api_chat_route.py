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


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("override_path", "route_path", "payload"),
    [
        (
            "tests/fixtures/config/api_streaming_enabled.yaml",
            "/api/v1/chat/stream",
            {"message": "stream route", "session_id": "session_api_stream_1"},
        ),
    ],
)
def test_stream_route_finalizes_workflow_state_in_real_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    override_path: str,
    route_path: str,
    payload: dict[str, str],
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", override_path)
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))
    workflow_database_path = tmp_path / "workflow_state.db"

    with TestClient(app) as client:
        response = client.post(
            route_path,
            headers={"x-trace-id": "trace-api-stream-0001"},
            json=payload,
        )

    assert response.status_code == 200
    assert response.headers["x-session-id"] == "session_api_stream_1"

    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    assert chunks[0].startswith("event: response.started\n")
    assert chunks[-1].startswith("event: response.completed\n")

    with sqlite3.connect(workflow_database_path) as connection:
        current_row = connection.execute(
            """
            SELECT message_count, state_json
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session_api_stream_1",),
        ).fetchone()

    assert current_row is not None
    assert current_row[0] == 2
    saved_state = json.loads(current_row[1])
    messages = saved_state["conversation"]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "stream route"
    assert isinstance(messages[0].get("created_at"), str)
    assert messages[0]["metadata"] == {
        "transport": "streaming",
        "usecase": "default_chat",
        "request_id": "trace-api-stream-0001",
        "turn_id": "trace-api-stream-0001",
        "trace_id": "trace-api-stream-0001",
    }
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "fake response"
    assert isinstance(messages[1].get("created_at"), str)
    assert messages[1]["metadata"] == {
        "agent_name": "support_agent",
        "strategy_name": "direct_agent",
        "llm_profile": "fake_streaming",
        "request_id": "trace-api-stream-0001",
        "turn_id": "trace-api-stream-0001",
        "trace_id": "trace-api-stream-0001",
        "transport": "streaming",
        "usecase": "default_chat",
    }


def test_history_route_returns_safe_messages_after_chat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/session_history_enabled.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        chat = client.post(
            "/chat",
            headers={"x-trace-id": "trace-api-history-chat-0001"},
            json={"message": "history me", "session_id": "session_api_history_1"},
        )
        history = client.get(
            "/sessions/session_api_history_1/history",
            headers={"x-trace-id": "trace-api-history-read-0001"},
            params={"limit": 2},
        )

    assert chat.status_code == 200
    assert history.status_code == 200
    assert history.headers["x-trace-id"] == "trace-api-history-read-0001"
    assert history.headers["x-session-id"] == "session_api_history_1"
    payload = history.json()
    assert payload["schema_version"] == "1.0"
    assert payload["trace_id"] == "trace-api-history-read-0001"
    assert payload["session_id"] == "session_api_history_1"
    assert payload["metadata"] == {"limit": 2, "returned_count": 2}
    assert payload["data"]["truncated"] is False
    messages = payload["data"]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "history me"
    assert isinstance(messages[0]["created_at"], str)
    assert messages[0]["metadata"] == {
        "message_chars": 10,
        "trace_id": "trace-api-history-chat-0001",
        "transport": "request/response",
        "usecase": "default_chat",
    }
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "fake response"
    assert isinstance(messages[1]["created_at"], str)
    assert messages[1]["metadata"] == {
        "message_chars": 13,
        "trace_id": "trace-api-history-chat-0001",
        "transport": "request/response",
        "usecase": "default_chat",
    }


def test_chat_route_degrades_to_fallback_when_primary_llm_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "config/app.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1/v1")
    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-trace-id": "trace-api-fallback-0001"},
            json={"message": "hello fallback", "session_id": "session_api_fallback_1"},
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-api-fallback-0001"
    assert response.headers["x-session-id"] == "session_api_fallback_1"
    assert response.json()["data"]["answer"] == (
        "I could not complete the full workflow, but here is the safest answer I can provide."
    )
    assert response.json()["data"]["strategy_name"] == "fallback_answer"
    assert response.json()["metadata"]["usecase"] == "default_chat"
    assert response.json()["metadata"]["message_count"] == 2
