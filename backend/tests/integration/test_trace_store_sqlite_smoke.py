from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.contracts.trace import TraceEvent
from app.main import create_app
from app.persistence.sqlite_trace_store import SqliteTraceStore
from app.persistence.trace_store import resolve_trace_store_path


@pytest.mark.asyncio
async def test_sqlite_trace_store_records_event(tmp_path) -> None:
    database_path = tmp_path / "trace-smoke.db"
    store = SqliteTraceStore(database_path)

    await store.initialize()
    await store.record_event(
        TraceEvent(
            trace_id=f"trace_{uuid4().hex}",
            session_id="session_123",
            event_type="request_received",
            component="api.health",
            timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
            payload={"status_code": 200},
        )
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT trace_id, event_type, component, payload_json FROM trace_events"
        ).fetchone()

    assert row is not None
    assert row[1] == "request_received"
    assert row[2] == "api.health"
    assert json.loads(row[3]) == {"status_code": 200}


def test_trace_schema_bootstrap_runs_during_lifespan_startup(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))
    database_path = resolve_trace_store_path(app.state.container.config) if app.state.container else tmp_path / "trace.db"
    assert not database_path.exists()

    with TestClient(app):
        assert database_path.exists()