from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


GENERATED_TRACE_ID_PATTERN = re.compile(r"^trace_[0-9a-f]{32}$")

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


def test_chat_route_preserves_valid_client_trace_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-trace-id": "trace-chat-1234"},
            json={"message": "hello"},
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-chat-1234"
    assert response.headers["x-session-id"] == response.json()["session_id"]
    assert response.json()["trace_id"] == "trace-chat-1234"


def test_chat_route_replaces_invalid_client_trace_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-trace-id": "Bearer secret token"},
            json={"message": "hello"},
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] != "Bearer secret token"
    assert GENERATED_TRACE_ID_PATTERN.fullmatch(response.headers["x-trace-id"])
    assert response.json()["trace_id"] == response.headers["x-trace-id"]