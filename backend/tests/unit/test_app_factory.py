import json
import logging
import re
import sqlite3

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.contracts.errors import ConfigurationError
from app.config.settings import load_settings
from app.main import create_app
from app.observability.metrics import InMemoryMetricsRecorder
from app.persistence.trace_store import resolve_trace_store_path


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


def build_test_settings(monkeypatch: pytest.MonkeyPatch):
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return load_settings(env_file=None)


def test_create_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = build_test_settings(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))

    assert app.title == settings.app_name
    assert app.version == settings.app_version

    with TestClient(app):
        assert app.state.container.settings.app_name == settings.app_name
        assert app.state.container.config.require("app.active_usecase") == "default_chat"
        assert app.state.container.config_summary["configured"] is True
        assert app.state.container.persistence.workflow_state is app.state.container.workflow_state
        assert app.state.container.persistence.trace_store is app.state.container.trace_store
        assert app.state.container.persistence.memory is app.state.container.memory


def test_trace_id_header(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-test-123"})

        assert response.status_code == 200
        assert response.headers["x-trace-id"] == "trace-test-123"

        aliased_response = client.get("/health", headers={"x-request-id": "trace-alias-456"})

        assert aliased_response.status_code == 200
        assert aliased_response.headers["x-trace-id"] == "trace-alias-456"

        generated_response = client.get("/health")

        assert generated_response.status_code == 200
        assert GENERATED_TRACE_ID_PATTERN.fullmatch(generated_response.headers["x-trace-id"])


def test_request_observability_events_and_metrics(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))
    database_path = resolve_trace_store_path(app.state.container.config) if app.state.container else tmp_path / "trace.db"
    snapshot = None

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "trace-test-123"})

        assert response.status_code == 200

        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                "SELECT event_name, component, trace_id, payload_json FROM trace_events ORDER BY created_at ASC, trace_id ASC, sequence_no ASC"
            ).fetchall()

        metrics = app.state.container.metrics
        assert isinstance(metrics, InMemoryMetricsRecorder)
        snapshot = metrics.snapshot()

    request_received = [row for row in rows if row[0] == "request_received"]
    response_returned = [row for row in rows if row[0] == "response_returned"]
    health_checked = [row for row in rows if row[0] == "health_checked"]

    assert request_received
    assert response_returned
    assert health_checked
    assert request_received[-1][2] == "trace-test-123"
    assert response_returned[-1][2] == "trace-test-123"
    assert json.loads(request_received[-1][3]) == {
        "method": "GET",
        "route_template": "/health",
        "streaming": False,
    }
    assert json.loads(response_returned[-1][3]) == {
        "method": "GET",
        "route_template": "/health",
        "status_code": 200,
        "duration_ms": json.loads(response_returned[-1][3])["duration_ms"],
        "streaming": False,
    }
    assert json.loads(response_returned[-1][3])["duration_ms"] >= 0

    assert snapshot is not None
    assert any(sample.name == "backend.requests.total" for sample in snapshot["counters"])
    assert any(sample.name == "backend.requests.duration_ms" for sample in snapshot["timings"])


def test_invalid_trace_id_header_is_replaced(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))
    database_path = resolve_trace_store_path(app.state.container.config) if app.state.container else tmp_path / "trace.db"

    with TestClient(app) as client:
        response = client.get("/health", headers={"x-trace-id": "Bearer secret token"})

        assert response.status_code == 200
        assert response.headers["x-trace-id"] != "Bearer secret token"
        assert GENERATED_TRACE_ID_PATTERN.fullmatch(response.headers["x-trace-id"])

        with sqlite3.connect(database_path) as connection:
            trace_id = connection.execute(
                "SELECT trace_id FROM trace_events WHERE event_name = 'request_received' ORDER BY created_at DESC, trace_id DESC, sequence_no DESC LIMIT 1"
            ).fetchone()[0]

    assert trace_id == response.headers["x-trace-id"]


def test_not_found_error_includes_trace_id(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.get("/missing")

        assert response.status_code == 404
        assert response.json() == {
            "schema_version": "1.0",
            "trace_id": response.headers["x-trace-id"],
            "error": {
                "code": "not_found",
                "message": "Resource not found.",
                "retryable": False,
                "details": {},
            },
        }


def test_create_app_fails_during_startup_for_invalid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    build_test_settings(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/invalid_missing_env.yaml")

    app = create_app(load_settings(env_file=None))

    with pytest.raises(ConfigurationError, match="REQUIRED_LLM_BASE_URL"):
        with TestClient(app):
            pass


def test_unhandled_error_returns_stable_json_and_trace_safe_observability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    app = create_app(load_settings(env_file=None))
    router = APIRouter()
    database_path = resolve_trace_store_path(app.state.container.config) if app.state.container else tmp_path / "trace.db"

    @router.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("Bearer secret-token")

    app.include_router(router)

    with caplog.at_level(logging.ERROR):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom", headers={"x-trace-id": "trace-error-123"})

            assert response.status_code == 500
            assert response.headers["x-trace-id"] == "trace-error-123"
            assert response.json() == {
                "schema_version": "1.0",
                "trace_id": "trace-error-123",
                "error": {
                    "code": "internal_error",
                    "message": "An internal server error occurred.",
                    "retryable": False,
                    "details": {},
                },
            }

        with sqlite3.connect(database_path) as connection:
            payload_json = connection.execute(
                "SELECT payload_json FROM trace_events WHERE event_name = 'error_occurred' ORDER BY created_at DESC, trace_id DESC, sequence_no DESC LIMIT 1"
            ).fetchone()[0]

    payload = json.loads(payload_json)
    assert payload["error_type"] == "RuntimeError"
    assert payload["details"] == {
        "method": "GET",
        "route_template": "/boom",
        "status_code": 500,
        "error_code": "internal_error",
    }
    assert "secret-token" not in payload_json
    assert "secret-token" not in caplog.text