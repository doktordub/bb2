from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
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


def build_test_settings(monkeypatch: pytest.MonkeyPatch):
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return load_settings(env_file=None)


def test_create_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_test_settings(monkeypatch)

    app = create_app(settings)

    assert app.title == settings.app_name
    assert app.version == settings.app_version
    assert app.state.container.settings == settings


def test_trace_id_header(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(build_test_settings(monkeypatch))
    client = TestClient(app)

    response = client.get("/health", headers={"x-trace-id": "trace-test-123"})

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-test-123"

    generated_response = client.get("/health")

    assert generated_response.status_code == 200
    UUID(generated_response.headers["x-trace-id"])


def test_not_found_error_includes_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(build_test_settings(monkeypatch))
    client = TestClient(app)

    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Resource not found.",
            "trace_id": response.headers["x-trace-id"],
            "details": {},
        }
    }