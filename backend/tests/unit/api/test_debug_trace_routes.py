from __future__ import annotations

from dataclasses import replace
from typing import Any

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


def build_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    override_path: str | None = None,
) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    if override_path is not None:
        monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", override_path)
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_debug_trace_routes_are_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/debug/traces")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_debug_trace_routes_bound_limits_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(
        monkeypatch,
        tmp_path,
        override_path="tests/fixtures/config/api_debug_traces_enabled.yaml",
    )

    class CapturingDebugTraceService:
        def __init__(self) -> None:
            self.read_limits: list[int | None] = []
            self.search_limits: list[int | None] = []

        async def read_trace(self, *, trace_id: str, limit: int | None = None) -> dict[str, Any]:
            self.read_limits.append(limit)
            return {
                "found": True,
                "data": {
                    "summary": {"trace_id": trace_id, "status": "completed"},
                    "events": [],
                },
                "metadata": {
                    "limit": 100,
                    "returned_events": 0,
                    "total_events": 0,
                    "truncated": False,
                },
            }

        async def search_traces(self, *, limit: int | None = None, **_: object) -> dict[str, Any]:
            self.search_limits.append(limit)
            return {
                "data": {"traces": []},
                "metadata": {"limit": 25, "result_count": 0},
            }

    service = CapturingDebugTraceService()

    with TestClient(app) as client:
        app.state.container = replace(app.state.container, debug_trace_service=service)
        read_response = client.get("/debug/traces/trace-debug-1234", params={"limit": 9999})
        search_response = client.get("/debug/traces", params={"limit": 9999})

    assert read_response.status_code == 200
    assert search_response.status_code == 200
    assert read_response.json()["metadata"]["limit"] == 100
    assert search_response.json()["metadata"]["limit"] == 25
    assert service.read_limits == [9999]
    assert service.search_limits == [9999]