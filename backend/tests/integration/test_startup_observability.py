from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.persistence.trace_store import resolve_trace_store_path


def test_observability_wiring_runs_during_lifespan_startup(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    app = create_app(load_settings(env_file=None))
    database_path = resolve_trace_store_path(app.state.container.config) if app.state.container else tmp_path / "trace.db"

    assert app.state.container is None
    assert not database_path.exists()

    with TestClient(app):
        assert app.state.container is not None
        assert database_path.exists()

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT trace_id, event_name, component, payload_json FROM trace_events WHERE event_name = 'startup_completed' ORDER BY created_at DESC, trace_id DESC, sequence_no DESC LIMIT 1"
        ).fetchone()

    assert row is not None
    assert row[0].startswith("trace_")
    assert row[1] == "startup_completed"
    assert row[2] == "backend.startup"
    payload = json.loads(row[3])
    assert payload == {}