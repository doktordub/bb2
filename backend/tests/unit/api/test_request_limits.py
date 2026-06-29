from __future__ import annotations

from dataclasses import replace

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
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/api_small_request_limits.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_oversized_request_body_returns_stable_413(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, session_service=FakeSessionService())
        response = client.post("/chat", json={"message": "x" * 600})
        service = app.state.container.session_service

    assert response.status_code == 413
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": "request_too_large",
            "message": "The request body exceeds the configured size limit.",
            "retryable": False,
            "details": {"limit_bytes": 512},
        },
    }
    assert isinstance(service, FakeSessionService)
    assert service.invocations == []


def test_configured_message_limit_rejects_chat_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, session_service=FakeSessionService())
        response = client.post("/chat", json={"message": "x" * 129})
        service = app.state.container.session_service

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
                        "msg": "Value error, message exceeds the configured limit",
                        "type": "value_error",
                    }
                ]
            },
        },
    }
    assert isinstance(service, FakeSessionService)
    assert service.invocations == []