from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.deployment.process_control import ProcessControlService
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
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "tests/fixtures/config/api_debug_restart_enabled.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_restart_route_uses_process_control_service_and_returns_accepted_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    runtime_dir = Path(tmp_path) / "runtime"
    shutdown_calls: list[str] = []
    service = ProcessControlService(
        runtime_dir=runtime_dir,
        shutdown_handler=lambda: shutdown_calls.append("shutdown"),
    )

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            process_control_service=service,
        )
        response = client.post("/restart", headers={"x-trace-id": "trace-restart-flow"})

    assert response.status_code == 202
    assert response.headers["x-trace-id"] == "trace-restart-flow"
    assert response.json()["data"]["restart_requested"] is True
    assert shutdown_calls == ["shutdown"]

    signal_payload = json.loads((runtime_dir / "restart-request.json").read_text(encoding="utf-8"))
    assert signal_payload["trace_id"] == "trace-restart-flow"
    assert signal_payload["requested_by"] == "local_user"
    assert signal_payload["client_host"] == "testclient"