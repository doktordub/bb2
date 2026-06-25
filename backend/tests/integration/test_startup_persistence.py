from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.persistence.errors import (
    MemoryGatewayError,
    PersistenceConfigurationError,
    WorkflowStateMigrationError,
    WorkflowStateUnavailableError,
)


def test_persistence_wiring_runs_during_lifespan_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_sqlite_local.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))
    trace_database_path = tmp_path / "trace.db"
    workflow_database_path = tmp_path / "workflow_state.db"

    assert app.state.container is None
    assert not trace_database_path.exists()
    assert not workflow_database_path.exists()

    with TestClient(app):
        assert app.state.container is not None
        assert trace_database_path.exists()
        assert workflow_database_path.exists()

    with sqlite3.connect(workflow_database_path) as connection:
        workflow_sessions_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_sessions'"
        ).fetchone()
        workflow_state_current_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_state_current'"
        ).fetchone()
        workflow_state_resets_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_state_resets'"
        ).fetchone()
        workflow_schema = connection.execute(
            "SELECT version FROM schema_version WHERE name = 'workflow_state_store'"
        ).fetchone()

    with sqlite3.connect(trace_database_path) as connection:
        trace_schema = connection.execute(
            "SELECT version FROM schema_version WHERE name = 'trace_store'"
        ).fetchone()

    assert workflow_sessions_table == ("workflow_sessions",)
    assert workflow_state_current_table == ("workflow_state_current",)
    assert workflow_state_resets_table == ("workflow_state_resets",)
    assert workflow_schema == (2,)
    assert trace_schema == (1,)


def test_optional_memory_store_failure_degrades_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_memory_optional.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["persistence"] == {
        "status": "degraded",
        "configured": True,
        "required_components": 2,
        "optional_components": 1,
        "components": {
            "workflow_state": "ok",
            "trace": "ok",
            "memory": "degraded",
        },
    }
    assert payload["checks"]["memory"] == {
        "status": "degraded",
        "configured": True,
        "provider": "memory_store",
        "required": False,
        "config_path_configured": True,
        "database_path_configured": False,
        "service_initialized": False,
        "reason": "config_path_missing",
        "error_type": "FileNotFoundError",
    }


def test_required_memory_store_failure_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_required_store_failure.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with pytest.raises(MemoryGatewayError, match="Memory gateway initialization failed"):
        with TestClient(app):
            pass


def test_invalid_persistence_provider_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_invalid_provider.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with pytest.raises(PersistenceConfigurationError, match="Unsupported memory gateway provider"):
        with TestClient(app):
            pass


def test_fake_persistence_fixture_starts_without_local_databases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_fake.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["workflow_state"]["provider"] == "fake"
    assert payload["checks"]["trace"]["provider"] == "fake"
    assert payload["checks"]["memory"]["provider"] == "fake"
    assert not (tmp_path / "trace.db").exists()
    assert not (tmp_path / "workflow_state.db").exists()


def test_unavailable_workflow_state_store_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "workflow_state.db").mkdir()

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_sqlite_local.yaml")
    monkeypatch.setenv("APP_DATA_DIR", runtime_dir.as_posix())

    app = create_app(load_settings(env_file=None))

    with pytest.raises(WorkflowStateUnavailableError, match="initialization failed"):
        with TestClient(app):
            pass


def test_workflow_state_schema_mismatch_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    workflow_database_path = runtime_dir / "workflow_state.db"
    with sqlite3.connect(workflow_database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO schema_version (name, version, applied_at)
            VALUES ('workflow_state_store', 999, '2026-06-24T12:00:00+00:00')
            """
        )
        connection.commit()

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/persistence_sqlite_local.yaml")
    monkeypatch.setenv("APP_DATA_DIR", runtime_dir.as_posix())

    app = create_app(load_settings(env_file=None))

    with pytest.raises(WorkflowStateMigrationError, match="schema version is unsupported"):
        with TestClient(app):
            pass