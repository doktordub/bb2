from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite.migrations import get_schema_version
from app.persistence.sqlite_trace_schema import (
    TRACE_SCHEMA_NAME,
    TRACE_SCHEMA_VERSION,
    ensure_trace_schema,
)


def test_trace_schema_initializer_is_idempotent_and_creates_expected_objects(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trace-schema.db"
    settings = _build_settings(database_path)

    with open_sqlite_connection(database_path, settings=settings) as connection:
        ensure_trace_schema(connection)
        ensure_trace_schema(connection)
        connection.commit()

        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_trace_%'"
            ).fetchall()
        }
        run_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info('trace_runs')").fetchall()
        }
        event_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info('trace_events')").fetchall()
        }

    assert tables >= {
        "schema_version",
        "trace_runs",
        "trace_events",
        "trace_retention_runs",
    }
    assert indexes >= {
        "idx_trace_runs_started_at",
        "idx_trace_runs_last_event_at",
        "idx_trace_runs_status",
        "idx_trace_runs_usecase",
        "idx_trace_runs_session_hash",
        "idx_trace_runs_error_type",
        "idx_trace_events_trace_sequence",
        "idx_trace_events_timestamp",
        "idx_trace_events_event_name",
        "idx_trace_events_event_type",
        "idx_trace_events_status",
        "idx_trace_events_agent_name",
        "idx_trace_events_llm_profile",
        "idx_trace_events_tool_name",
        "idx_trace_events_error_type",
    }
    assert run_columns >= {
        "trace_id",
        "status",
        "started_at",
        "last_event_at",
        "event_count",
        "error_count",
        "metadata_json",
        "provider",
        "model",
    }
    assert event_columns >= {
        "event_id",
        "trace_id",
        "sequence_no",
        "component",
        "payload_json",
        "payload_size_bytes",
        "redaction_version",
    }
    assert _get_schema_version_for_file(database_path) == TRACE_SCHEMA_VERSION


def test_trace_schema_migrates_legacy_trace_events_table(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-legacy.db"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_id TEXT NULL,
                usecase TEXT NULL,
                event_type TEXT NOT NULL,
                component TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        connection.execute(
            """
            INSERT INTO trace_events (
                trace_id,
                session_id,
                user_id,
                usecase,
                event_type,
                component,
                timestamp,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trace_legacy",
                "session_123",
                "user_123",
                "chat",
                "request_received",
                "api.health",
                datetime(2026, 6, 24, 23, 0, tzinfo=UTC).isoformat(),
                json.dumps({"route_template": "/health", "status_code": 200}),
            ),
        )
        connection.commit()

    settings = _build_settings(database_path)
    with open_sqlite_connection(database_path, settings=settings) as connection:
        ensure_trace_schema(connection)
        connection.commit()

        backup_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trace_events_legacy_v1'"
        ).fetchone()
        run_row = connection.execute(
            """
            SELECT trace_id, usecase, status, event_count, error_count
            FROM trace_runs
            WHERE trace_id = 'trace_legacy'
            """
        ).fetchone()
        event_row = connection.execute(
            """
            SELECT event_id, sequence_no, event_name, event_type, component, payload_json
            FROM trace_events
            WHERE trace_id = 'trace_legacy'
            """
        ).fetchone()

    assert backup_table == ("trace_events_legacy_v1",)
    assert run_row == ("trace_legacy", "chat", "completed", 1, 0)
    assert event_row is not None
    assert event_row[0] == "legacy_event_1"
    assert event_row[1] == 1
    assert event_row[2] == "request_received"
    assert event_row[3] == "request_received"
    assert event_row[4] == "api.health"
    assert json.loads(str(event_row[5])) == {
        "route_template": "/health",
        "status_code": 200,
    }
    assert _get_schema_version_for_file(database_path) == TRACE_SCHEMA_VERSION


def _build_settings(database_path: Path) -> SqliteTraceStoreSettings:
    return SqliteTraceStoreSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
        max_event_payload_bytes=32768,
        max_error_detail_bytes=4096,
        max_events_per_trace_read=1000,
        max_search_results=200,
        store_raw_session_id=False,
        store_session_id_hash=True,
        store_raw_user_id=False,
        store_user_id_hash=True,
        capture_request_body=False,
        capture_response_body=False,
        capture_llm_prompts=False,
        capture_llm_completions=False,
        capture_tool_payloads="summaries_only",
        capture_memory_queries="summaries_only",
        retention_enabled=False,
        retention_keep_days=30,
        retention_cleanup_batch_size=1000,
    )


def _get_schema_version_for_file(database_path: Path) -> int | None:
    with open_sqlite_connection(database_path, settings=_build_settings(database_path)) as connection:
        return get_schema_version(connection, name=TRACE_SCHEMA_NAME)