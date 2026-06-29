from __future__ import annotations

import json
import signal
from dataclasses import replace
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.deployment.process_control import (
    ProcessControlService,
    RestartLaunchSpec,
    _build_restart_helper_command,
    build_self_relaunch_handler,
)
from app.main import create_app, _resolve_restart_command


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
    override_path: str = "tests/fixtures/config/api_debug_restart_enabled.yaml",
) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", override_path)
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_restart_route_returns_not_found_when_restart_route_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(
        monkeypatch,
        tmp_path,
        override_path="tests/fixtures/config/api_debug_traces_enabled.yaml",
    )

    with TestClient(app) as client:
        response = client.post("/restart")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_restart_route_returns_service_unavailable_without_runtime_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/restart", headers={"x-trace-id": "trace-restart-1234"})

    assert response.status_code == 503
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": "trace-restart-1234",
        "error": {
            "code": "restart_unavailable",
            "message": "Backend restart is not configured for the current runtime.",
            "retryable": False,
            "details": {},
        },
    }


def test_restart_route_auto_binds_uvicorn_runtime_shutdown_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    relaunched: list[tuple[tuple[str, ...], int]] = []

    class _FakeUvicornHandler:
        __module__ = "uvicorn.server"

        def __call__(self, sig: int, frame: object | None) -> None:
            return None

    original_getsignal = signal.getsignal

    def _fake_getsignal(sig: int) -> object:
        if sig == signal.SIGTERM:
            return _FakeUvicornHandler()
        return original_getsignal(sig)

    monkeypatch.setattr(signal, "getsignal", _fake_getsignal)
    monkeypatch.setattr(
        "app.deployment.process_control._spawn_restart_helper",
        lambda *, launch_spec, parent_pid: relaunched.append((launch_spec.command, parent_pid)),
    )
    monkeypatch.setattr(signal, "raise_signal", lambda sig: relaunched.append((("signal", str(sig)), -1)))

    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        expected_signal_path = app.state.container.process_control_service.signal_path.as_posix()
        response = client.post("/restart", headers={"x-trace-id": "trace-restart-auto"})

    assert response.status_code == 202
    payload = response.json()
    assert payload["trace_id"] == "trace-restart-auto"
    assert payload["data"]["restart_requested"] is True
    assert payload["data"]["signal_path"] == expected_signal_path
    assert relaunched[0][0] == _resolve_restart_command(settings=load_settings(env_file=None))
    assert relaunched[1] == (("signal", str(signal.SIGTERM)), -1)


def test_restart_route_accepts_request_and_records_signal_when_runtime_handler_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)
    shutdown_calls: list[str] = []
    runtime_dir = Path(tmp_path) / "runtime"
    service = ProcessControlService(
        runtime_dir=runtime_dir,
        shutdown_handler=lambda: shutdown_calls.append("shutdown"),
    )

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            process_control_service=service,
        )
        response = client.post("/restart", headers={"x-trace-id": "trace-restart-ok"})

    assert response.status_code == 202
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["trace_id"] == "trace-restart-ok"
    assert payload["data"]["restart_requested"] is True
    assert payload["data"]["signal_path"] == (runtime_dir / "restart-request.json").as_posix()
    assert payload["metadata"] == {
        "graceful_shutdown_requested": True,
        "reason": None,
    }
    assert shutdown_calls == ["shutdown"]

    signal_payload = json.loads((runtime_dir / "restart-request.json").read_text(encoding="utf-8"))
    assert signal_payload["trace_id"] == "trace-restart-ok"
    assert signal_payload["route_path"] == "/restart"
    assert signal_payload["graceful_shutdown_requested"] is True


def test_build_self_relaunch_handler_spawns_helper_before_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    helper_calls: list[tuple[tuple[str, ...], int]] = []
    raised_signals: list[int] = []

    monkeypatch.setattr(
        "app.deployment.process_control._spawn_restart_helper",
        lambda *, launch_spec, parent_pid: helper_calls.append((launch_spec.command, parent_pid)),
    )
    monkeypatch.setattr(signal, "raise_signal", lambda sig: raised_signals.append(sig))

    handler = build_self_relaunch_handler(
        launch_spec=type("Spec", (), {"command": ("python", "-m", "uvicorn"), "working_dir": "E:/tmp"})(),
        shutdown_signal=signal.SIGTERM,
    )

    handler()

    assert helper_calls
    assert helper_calls[0][0] == ("python", "-m", "uvicorn")
    assert raised_signals == [signal.SIGTERM]


def test_resolve_restart_command_prefers_original_uvicorn_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.orig_argv",
        [
            "E:/KODE/tools/bb2/backend/.venv/Scripts/python.exe",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8015",
        ],
        raising=False,
    )

    settings = load_settings(env_file=None)

    assert _resolve_restart_command(settings=settings) == (
        "E:/KODE/tools/bb2/backend/.venv/Scripts/python.exe",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8015",
    )


def test_restart_helper_command_prefers_original_python_launcher() -> None:
    command = _build_restart_helper_command(
        launch_spec=RestartLaunchSpec(
            command=(
                "E:/KODE/tools/bb2/backend/.venv/Scripts/python.exe",
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8017",
            ),
            working_dir="E:/KODE/tools/bb2/backend",
        ),
        parent_pid=12345,
    )

    assert command[0] == "E:/KODE/tools/bb2/backend/.venv/Scripts/python.exe"
    assert command[1:3] == ("-m", "app.deployment.restart_helper")