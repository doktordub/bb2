"""SQLite schema bootstrap for append-only trace persistence."""

from app.persistence.sqlite.migrations import SupportsMigration, ensure_schema

TRACE_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_events (
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

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_id
    ON trace_events(trace_id);

CREATE INDEX IF NOT EXISTS idx_trace_events_session_id
    ON trace_events(session_id);

CREATE INDEX IF NOT EXISTS idx_trace_events_timestamp
    ON trace_events(timestamp);
"""
TRACE_SCHEMA_NAME = "trace_store"
TRACE_SCHEMA_VERSION = 1


def ensure_trace_schema(connection: SupportsMigration) -> None:
    """Create the initial trace schema when it is missing."""

    ensure_schema(
        connection,
        name=TRACE_SCHEMA_NAME,
        target_version=TRACE_SCHEMA_VERSION,
        apply_schema=_apply_trace_schema,
    )


def _apply_trace_schema(connection: SupportsMigration) -> None:
    connection.executescript(TRACE_EVENTS_SCHEMA)