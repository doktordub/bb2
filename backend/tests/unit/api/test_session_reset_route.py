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


def test_reset_route_clears_fake_session_state_and_returns_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        chat = client.post("/chat", json={"message": "hello", "session_id": "session_123"})
        assert chat.status_code == 200

        response = client.post(
            "/sessions/session_123/reset",
            headers={"x-trace-id": "trace-reset-1234"},
            json={"reason": "user_requested"},
        )
        service = cast(FakeSessionService, app.state.container.session_service)

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-reset-1234"
    assert response.headers["x-session-id"] == "session_123"
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": "trace-reset-1234",
        "session_id": "session_123",
        "data": {
            "reset": True,
            "message": "Session workflow state was reset.",
        },
        "metadata": {"reason": "user_requested"},
    }
    assert "session_123" not in service.states
    assert service.invocations[-1].kind == "reset_session"
    assert service.invocations[-1].metadata == {"reason": "user_requested"}


def test_reset_route_invalid_session_id_returns_stable_400(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/sessions/bad id/reset", json={})

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
                        "loc": ["path", "session_id"],
                        "msg": "Value error, invalid session_id",
                        "type": "value_error",
                    }
                ]
            },
        },
    }