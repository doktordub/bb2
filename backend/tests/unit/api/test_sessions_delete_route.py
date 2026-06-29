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
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "tests/fixtures/config/session_management_enabled.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_delete_session_route_returns_stable_envelope_and_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        service = FakeSessionService()
        app.state.container = replace(app.state.container, session_service=service)
        client.post("/chat", json={"message": "hello", "session_id": "session_123"})

        response = client.delete("/sessions/session_123", headers={"x-trace-id": "trace-delete-1234"})

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-delete-1234"
    assert response.headers["x-session-id"] == "session_123"
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": "trace-delete-1234",
        "session_id": "session_123",
        "data": {
            "deleted": True,
            "message": "Session workflow state was deleted.",
        },
        "metadata": {"deleted": True},
    }
    assert service.invocations[-1].kind == "delete_session"


def test_delete_session_route_returns_stable_404_for_unknown_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, session_service=FakeSessionService())
        response = client.delete("/sessions/missing_session")

    assert response.status_code == 404
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": "session_not_found",
            "message": "The requested session was not found.",
            "retryable": False,
            "details": {},
        },
    }