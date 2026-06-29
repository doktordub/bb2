from __future__ import annotations

from dataclasses import replace
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


def test_chat_route_returns_response_headers_and_calls_service_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, session_service=FakeSessionService())
        response = client.post(
            "/chat",
            headers={"x-trace-id": "trace-chat-route-1234"},
            json={
                "message": "hello route",
                "session_id": "session_123",
                "usecase": "support_chat",
                "metadata": {"client": "web"},
            },
        )
        service = cast(FakeSessionService, app.state.container.session_service)

        assert response.status_code == 200
        assert response.headers["x-trace-id"] == "trace-chat-route-1234"
        assert response.headers["x-session-id"] == "session_123"
        assert response.json() == {
            "schema_version": "1.0",
            "trace_id": "trace-chat-route-1234",
            "session_id": "session_123",
            "data": {
                "answer": "Echo: hello route",
                "agent_name": "fake_session_agent",
                "strategy_name": "fake_direct_strategy",
                "llm_profile": "fake_local_profile",
                "tool_calls": [],
                "memory_updates": [],
            },
            "metadata": {
                "usecase": "support_chat",
                "message_count": 2,
                "message_count_before": 0,
            },
        }
        assert len(service.invocations) == 1
        assert service.invocations[0].kind == "handle_chat"
        assert service.invocations[0].session_id == "session_123"
        assert service.invocations[0].trace_id == "trace-chat-route-1234"


def test_chat_route_accepts_session_header_when_body_session_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, session_service=FakeSessionService())
        response = client.post(
            "/chat",
            headers={"x-session-id": "session_from_header"},
            json={"message": "hello header"},
        )

    assert response.status_code == 200
    assert response.headers["x-session-id"] == "session_from_header"
    assert response.json()["session_id"] == "session_from_header"


def test_chat_route_invalid_session_id_returns_stable_400(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"message": "hello", "session_id": "bad id with spaces"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": "invalid_session_id",
            "message": "The session ID is invalid.",
            "retryable": False,
            "details": {
                "errors": [
                    {
                        "loc": ["body", "session_id"],
                        "msg": "Value error, invalid session_id",
                        "type": "value_error",
                    }
                ]
            },
        },
    }