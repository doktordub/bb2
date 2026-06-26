from __future__ import annotations

from dataclasses import replace
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


def test_stream_route_returns_event_stream_and_sets_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            headers={"x-trace-id": "trace-stream-route-1234"},
            json={"message": "hello stream"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-trace-id"] == "trace-stream-route-1234"
    assert response.headers["x-session-id"].startswith("session_")

    events = _parse_sse_events(response.text)
    assert [event["event"] for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.completed",
    ]
    assert events[0]["data"] == {
        "schema_version": "1.0",
        "session_id": response.headers["x-session-id"],
    }
    assert events[1]["data"]["text"]
    assert events[2]["data"]["text"]
    assert events[3]["data"] == {
        "session_id": response.headers["x-session-id"],
        "finish_reason": "stop",
        "duration_ms": 0,
    }


def test_stream_route_emits_response_error_event_when_service_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    class FailingSessionService:
        async def handle_chat(self, **_: object) -> object:
            raise AssertionError("handle_chat should not be called")

        async def stream_chat(self, **_: object):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        async def reset_session(self, **_: object) -> object:
            raise AssertionError("reset_session should not be called")

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, session_service=FailingSessionService())
        response = client.post(
            "/api/v1/chat/stream",
            headers={"x-trace-id": "trace-stream-error-1234"},
            json={"message": "hello stream"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-trace-id"] == "trace-stream-error-1234"

    events = _parse_sse_events(response.text)
    assert len(events) == 1
    assert events[0]["event"] == "response.error"
    assert events[0]["data"] == {
        "trace_id": "trace-stream-error-1234",
        "error": {
            "code": "backend_error",
            "message": "The request failed.",
            "retryable": True,
        },
    }


def _parse_sse_events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for chunk in body.strip().split("\n\n"):
        if not chunk:
            continue
        parsed: dict[str, object] = {}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                parsed["event"] = line.removeprefix("event: ")
            elif line.startswith("data: "):
                parsed["data"] = json.loads(line.removeprefix("data: "))
        events.append(parsed)
    return events