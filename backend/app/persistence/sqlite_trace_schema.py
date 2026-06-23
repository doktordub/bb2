"""SQLite schema bootstrap for append-only trace persistence."""

from typing import Protocol

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


class SupportsExecuteScript(Protocol):
    def executescript(self, sql_script: str) -> object:
        ...


def ensure_trace_schema(connection: SupportsExecuteScript) -> None:
    """Create the initial trace schema when it is missing."""

    connection.executescript(TRACE_EVENTS_SCHEMA)