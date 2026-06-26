from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.testing.fakes.fake_session_service import FakeSessionService


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


def test_chat_route_round_trip_works_with_real_app_factory_and_fake_session_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        first = client.post(
            "/chat",
            headers={"x-trace-id": "trace-chat-int-0001"},
            json={"message": "hello integration"},
        )

        assert first.status_code == 200
        session_id = first.json()["session_id"]

        second = client.post(
            "/chat",
            headers={
                "x-trace-id": "trace-chat-int-0002",
                "x-session-id": session_id,
            },
            json={"message": "second turn"},
        )

        service = cast(FakeSessionService, app.state.container.session_service)

        assert second.status_code == 200
        assert second.headers["x-session-id"] == session_id
        assert second.json() == {
            "schema_version": "1.0",
            "trace_id": "trace-chat-int-0002",
            "session_id": session_id,
            "data": {
                "answer": "Echo: second turn",
                "agent_name": "fake_session_agent",
                "strategy_name": "fake_direct_strategy",
                "llm_profile": "fake_local_profile",
                "tool_calls": [],
                "memory_updates": [],
            },
            "metadata": {
                "usecase": None,
                "message_count": 4,
                "message_count_before": 2,
            },
        }
        assert list(service.states) == [session_id]
        assert len(service.states[session_id]["conversation"]["messages"]) == 4