"""SQLite schema bootstrap for operational trace persistence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.contracts.trace import TraceEvent, TraceSummary
from app.persistence.errors import TraceStoreMigrationError
from app.persistence.serialization import dumps_canonical_json
from app.persistence.sqlite.migrations import SupportsMigration, ensure_schema, table_exists

TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_runs (
    trace_id TEXT PRIMARY KEY,
    parent_trace_id TEXT NULL,
    session_id TEXT NULL,
    session_id_hash TEXT NULL,
    user_id TEXT NULL,
    user_id_hash TEXT NULL,
    usecase TEXT NULL,
    operation TEXT NULL,
    route_template TEXT NULL,
    status TEXT NOT NULL DEFAULT 'started',
    severity TEXT NOT NULL DEFAULT 'info',
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    last_event_at TEXT NOT NULL,
    duration_ms REAL NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    agent_name TEXT NULL,
    strategy_name TEXT NULL,
    llm_profile TEXT NULL,
    provider TEXT NULL,
    model TEXT NULL,
    tool_name TEXT NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    parent_event_id TEXT NULL,
    event_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    component TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    duration_ms REAL NULL,
    session_id TEXT NULL,
    session_id_hash TEXT NULL,
    user_id TEXT NULL,
    user_id_hash TEXT NULL,
    usecase TEXT NULL,
    agent_name TEXT NULL,
    strategy_name TEXT NULL,
    llm_profile TEXT NULL,
    provider TEXT NULL,
    model TEXT NULL,
    tool_name TEXT NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    retryable INTEGER NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    payload_size_bytes INTEGER NOT NULL DEFAULT 2,
    redaction_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trace_id)
        REFERENCES trace_runs(trace_id)
        ON DELETE CASCADE,
    UNIQUE(trace_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS trace_retention_runs (
    retention_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NULL,
    cutoff_at TEXT NOT NULL,
    deleted_trace_count INTEGER NOT NULL DEFAULT 0,
    deleted_event_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'started',
    error_type TEXT NULL,
    error_code TEXT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_runs_started_at
    ON trace_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_trace_runs_last_event_at
    ON trace_runs(last_event_at);

CREATE INDEX IF NOT EXISTS idx_trace_runs_status
    ON trace_runs(status);

CREATE INDEX IF NOT EXISTS idx_trace_runs_usecase
    ON trace_runs(usecase);

CREATE INDEX IF NOT EXISTS idx_trace_runs_session_hash
    ON trace_runs(session_id_hash);

CREATE INDEX IF NOT EXISTS idx_trace_runs_error_type
    ON trace_runs(error_type);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_sequence
    ON trace_events(trace_id, sequence_no);

CREATE INDEX IF NOT EXISTS idx_trace_events_timestamp
    ON trace_events(timestamp);

CREATE INDEX IF NOT EXISTS idx_trace_events_event_name
    ON trace_events(event_name);

CREATE INDEX IF NOT EXISTS idx_trace_events_event_type
    ON trace_events(event_type);

CREATE INDEX IF NOT EXISTS idx_trace_events_status
    ON trace_events(status);

CREATE INDEX IF NOT EXISTS idx_trace_events_agent_name
    ON trace_events(agent_name);

CREATE INDEX IF NOT EXISTS idx_trace_events_llm_profile
    ON trace_events(llm_profile);

CREATE INDEX IF NOT EXISTS idx_trace_events_tool_name
    ON trace_events(tool_name);

CREATE INDEX IF NOT EXISTS idx_trace_events_error_type
    ON trace_events(error_type);
"""
TRACE_SCHEMA_NAME = "trace_store"
TRACE_SCHEMA_VERSION = 2
LEGACY_TRACE_EVENTS_TABLE = "trace_events"
LEGACY_TRACE_EVENTS_BACKUP_TABLE = "trace_events_legacy_v1"


def ensure_trace_schema(connection: SupportsMigration) -> None:
    """Create or migrate the trace schema when it is missing or outdated."""

    ensure_schema(
        connection,
        name=TRACE_SCHEMA_NAME,
        target_version=TRACE_SCHEMA_VERSION,
        apply_schema=_apply_trace_schema,
    )


def _apply_trace_schema(connection: SupportsMigration) -> None:
    legacy_source_table = _resolve_legacy_source_table(connection)
    connection.executescript(TRACE_SCHEMA)
    if legacy_source_table is None:
        return

    _migrate_legacy_rows(connection, source_table=legacy_source_table)


def _resolve_legacy_source_table(connection: SupportsMigration) -> str | None:
    if table_exists(connection, name=LEGACY_TRACE_EVENTS_BACKUP_TABLE):
        return LEGACY_TRACE_EVENTS_BACKUP_TABLE

    if not table_exists(connection, name=LEGACY_TRACE_EVENTS_TABLE):
        return None

    if not _is_legacy_trace_events_table(connection, table_name=LEGACY_TRACE_EVENTS_TABLE):
        return None

    connection.execute(
        f"ALTER TABLE {LEGACY_TRACE_EVENTS_TABLE} RENAME TO {LEGACY_TRACE_EVENTS_BACKUP_TABLE}"
    )
    return LEGACY_TRACE_EVENTS_BACKUP_TABLE


def _is_legacy_trace_events_table(connection: SupportsMigration, *, table_name: str) -> bool:
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    }
    return "event_id" not in columns or "sequence_no" not in columns


def _migrate_legacy_rows(connection: SupportsMigration, *, source_table: str) -> None:
    rows = connection.execute(
        (
            "SELECT id, trace_id, session_id, user_id, usecase, event_type, "
            f"component, timestamp, payload_json FROM {source_table} ORDER BY trace_id, timestamp, id"
        )
    ).fetchall()

    events_by_trace: dict[str, list[TraceEvent]] = defaultdict(list)
    payloads_by_event_id: dict[str, tuple[str, int]] = {}

    for row in rows:
        (
            legacy_id,
            trace_id_value,
            session_id_value,
            user_id_value,
            usecase_value,
            event_type_value,
            component_value,
            timestamp_value,
            payload_json_value,
        ) = row

        trace_id = _require_text(trace_id_value, field_name="trace_id")
        timestamp = _decode_legacy_timestamp(timestamp_value, trace_id=trace_id)
        payload = _decode_legacy_payload(payload_json_value, trace_id=trace_id)
        session_id = _optional_text(session_id_value) or "unknown_session"
        user_id = _optional_text(user_id_value)
        usecase = _optional_text(usecase_value)
        event_name = _optional_text(event_type_value) or "legacy_event"
        component = _optional_text(component_value) or "legacy.trace"
        if isinstance(legacy_id, bool) or not isinstance(legacy_id, int):
            raise TraceStoreMigrationError(
                "Legacy trace row identifier is invalid.",
                details={"trace_id": trace_id},
            )
        event_id = f"legacy_event_{legacy_id}"
        status = _derive_legacy_status(event_name=event_name, payload=payload)
        severity = _derive_legacy_severity(status=status, payload=payload)
        error_type = _optional_text(payload.get("error_type"))
        error_code = _optional_text(payload.get("error_code"))
        retryable = _optional_bool(payload.get("retryable"))
        payload_json = dumps_canonical_json(payload)

        event = TraceEvent(
            trace_id=trace_id,
            session_id=session_id,
            event_type=event_name,
            component=component,
            timestamp=timestamp,
            event_name=event_name,
            status=status,
            severity=severity,
            event_id=event_id,
            session_id_hash=_hash_identifier(session_id),
            user_id=user_id,
            user_id_hash=_hash_identifier(user_id),
            usecase=usecase,
            provider=_optional_text(payload.get("provider")),
            model=_optional_text(payload.get("model")),
            tool_name=_optional_text(payload.get("tool_name")),
            error_type=error_type,
            error_code=error_code,
            retryable=retryable,
            payload=payload,
        )
        events_by_trace[trace_id].append(event)
        payloads_by_event_id[event_id] = (payload_json, len(payload_json.encode("utf-8")))

    for trace_id, events in events_by_trace.items():
        summary = TraceSummary.from_events(trace_id=trace_id, events=events)
        first_event = events[0]
        last_event = events[-1]

        connection.execute(
            """
            INSERT INTO trace_runs (
                trace_id,
                parent_trace_id,
                session_id,
                session_id_hash,
                user_id,
                user_id_hash,
                usecase,
                operation,
                route_template,
                status,
                severity,
                started_at,
                ended_at,
                last_event_at,
                duration_ms,
                event_count,
                error_count,
                agent_name,
                strategy_name,
                llm_profile,
                provider,
                model,
                tool_name,
                error_type,
                error_code,
                metadata_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.trace_id,
                summary.parent_trace_id,
                _last_non_empty_text(events, "session_id"),
                summary.session_id_hash,
                _last_non_empty_text(events, "user_id"),
                summary.user_id_hash,
                summary.usecase,
                summary.operation,
                summary.route_template,
                summary.status or "completed",
                summary.severity or "info",
                _isoformat_or_none(summary.started_at) or first_event.timestamp.isoformat(),
                _isoformat_or_none(summary.ended_at),
                _isoformat_or_none(summary.last_event_at) or last_event.timestamp.isoformat(),
                summary.duration_ms,
                summary.event_count,
                summary.error_count,
                summary.agent_name,
                summary.strategy_name,
                summary.llm_profile,
                _last_non_empty_text(events, "provider"),
                _last_non_empty_text(events, "model"),
                summary.tool_name,
                summary.error_type,
                summary.error_code,
                dumps_canonical_json(summary.metadata),
                first_event.timestamp.isoformat(),
                last_event.timestamp.isoformat(),
            ),
        )

        for sequence_no, event in enumerate(events, start=1):
            payload_json, payload_size_bytes = payloads_by_event_id[event.event_id or ""]
            connection.execute(
                """
                INSERT INTO trace_events (
                    event_id,
                    trace_id,
                    sequence_no,
                    parent_event_id,
                    event_name,
                    event_type,
                    status,
                    severity,
                    component,
                    timestamp,
                    duration_ms,
                    session_id,
                    session_id_hash,
                    user_id,
                    user_id_hash,
                    usecase,
                    agent_name,
                    strategy_name,
                    llm_profile,
                    provider,
                    model,
                    tool_name,
                    error_type,
                    error_code,
                    retryable,
                    payload_json,
                    payload_size_bytes,
                    redaction_version,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.trace_id,
                    sequence_no,
                    event.parent_event_id,
                    event.resolved_event_name,
                    event.event_type,
                    event.status,
                    event.severity,
                    event.component,
                    event.timestamp.isoformat(),
                    event.duration_ms,
                    event.session_id,
                    event.session_id_hash,
                    event.user_id,
                    event.user_id_hash,
                    event.usecase,
                    event.agent_name,
                    event.strategy_name,
                    event.llm_profile,
                    event.provider,
                    event.model,
                    event.tool_name,
                    event.error_type,
                    event.error_code,
                    _bool_to_sqlite(event.retryable),
                    payload_json,
                    payload_size_bytes,
                    1,
                    event.timestamp.isoformat(),
                ),
            )


def _require_text(value: object, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise TraceStoreMigrationError(
            f"Legacy trace-store {field_name} is not valid text."
        )
    return text


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _decode_legacy_timestamp(value: object, *, trace_id: str) -> datetime:
    if not isinstance(value, str):
        raise TraceStoreMigrationError(
            f"Legacy trace-store timestamp is not valid text for trace {trace_id!r}."
        )

    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TraceStoreMigrationError(
            f"Legacy trace-store timestamp is invalid for trace {trace_id!r}."
        ) from exc

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _decode_legacy_payload(value: object, *, trace_id: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise TraceStoreMigrationError(
            f"Legacy trace-store payload_json is not valid text for trace {trace_id!r}."
        )

    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TraceStoreMigrationError(
            f"Legacy trace-store payload_json contains invalid JSON for trace {trace_id!r}."
        ) from exc

    if isinstance(payload, Mapping):
        return {str(key): item for key, item in payload.items()}

    return {"value": payload}


def _derive_legacy_status(*, event_name: str, payload: Mapping[str, Any]) -> str:
    success = payload.get("success")
    if success is False:
        return "failed"
    if event_name == "error_occurred":
        return "failed"
    return "completed"


def _derive_legacy_severity(*, status: str, payload: Mapping[str, Any]) -> str:
    severity = _optional_text(payload.get("severity"))
    if severity is not None:
        return severity
    if status == "failed":
        return "error"
    return "info"


def _hash_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _last_non_empty_text(events: list[TraceEvent], attribute: str) -> str | None:
    for event in reversed(events):
        value = getattr(event, attribute)
        if isinstance(value, str) and value.strip() != "":
            return value
    return None


def _isoformat_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _bool_to_sqlite(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0