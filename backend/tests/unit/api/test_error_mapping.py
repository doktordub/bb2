from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.session.errors import SessionConflictError, SessionNotFoundError, UnknownUseCaseError


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


class RaisingChatSessionService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def handle_chat(self, **_: object) -> object:
        raise self._error

    async def reset_session(self, **_: object) -> object:
        raise self._error

    async def stream_chat(self, **_: object) -> object:
        raise self._error


def test_chat_validation_error_returns_stable_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "   "})

    assert response.status_code == 422
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": "validation_error",
            "message": "The request is invalid.",
            "retryable": False,
            "details": {
                "errors": [
                    {
                        "loc": ["body", "message"],
                        "msg": "Value error, message must not be empty",
                        "type": "value_error",
                    }
                ]
            },
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (SessionNotFoundError("missing"), 404, "session_not_found"),
        (SessionConflictError("conflict"), 409, "session_conflict"),
        (UnknownUseCaseError("unknown"), 400, "unknown_usecase"),
    ],
)
def test_known_session_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = client.post(
            "/chat",
            json={"message": "hello", "session_id": "session_123"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": False,
            "details": {},
        },
    }