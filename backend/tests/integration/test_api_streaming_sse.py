from __future__ import annotations

import json

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


def build_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/api_streaming_enabled.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_streaming_route_returns_well_formed_sse_from_real_app_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            headers={"x-trace-id": "trace-stream-int-0001"},
            json={"message": "stream me"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-trace-id"] == "trace-stream-int-0001"
    assert response.headers["x-session-id"].startswith("session_")

    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    assert chunks[0].startswith("event: response.started\n")
    assert chunks[-1].startswith("event: response.completed\n")

    payloads = [
        json.loads(next(line for line in chunk.splitlines() if line.startswith("data: ")).removeprefix("data: "))
        for chunk in chunks
    ]
    assert payloads[0]["session_id"] == response.headers["x-session-id"]
    assert all("trace_id" not in payload for payload in payloads if payload is not payloads[-1])
    assert payloads[-1]["session_id"] == response.headers["x-session-id"]