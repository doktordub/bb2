"""SQLite schema bootstrap for workflow-state persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from app.persistence.errors import WorkflowStateMigrationError
from app.persistence.serialization import (
    dumps_canonical_json,
    extract_checkpoint_name,
    extract_current_step,
    extract_message_count,
    hash_canonical_json,
)
from app.persistence.sqlite.migrations import (
    SupportsMigration,
    ensure_schema,
    table_exists,
)

WORKFLOW_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NULL,
    user_id_hash TEXT NULL,
    usecase TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    reset_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workflow_state_current (
    session_id TEXT PRIMARY KEY,
    state_version INTEGER NOT NULL DEFAULT 1,
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    state_size_bytes INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    current_step TEXT NULL,
    checkpoint_name TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reset_generation INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id)
        REFERENCES workflow_sessions(session_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workflow_state_resets (
    reset_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NULL,
    reason TEXT NULL,
    reset_generation INTEGER NOT NULL,
    cleared_state_version INTEGER NULL,
    reset_at TEXT NOT NULL,
    FOREIGN KEY (session_id)
        REFERENCES workflow_sessions(session_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_user_hash
    ON workflow_sessions(user_id_hash);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_usecase
    ON workflow_sessions(usecase);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_last_activity
    ON workflow_sessions(last_activity_at);

CREATE INDEX IF NOT EXISTS idx_workflow_state_updated_at
    ON workflow_state_current(updated_at);

CREATE INDEX IF NOT EXISTS idx_workflow_state_current_step
    ON workflow_state_current(current_step);

CREATE INDEX IF NOT EXISTS idx_workflow_resets_session_id
    ON workflow_state_resets(session_id);

CREATE INDEX IF NOT EXISTS idx_workflow_resets_reset_at
    ON workflow_state_resets(reset_at);
"""
WORKFLOW_STATE_SCHEMA_NAME = "workflow_state_store"
WORKFLOW_STATE_SCHEMA_VERSION = 2
LEGACY_WORKFLOW_STATE_TABLE = "workflow_states"
LEGACY_WORKFLOW_STATE_BACKUP_TABLE = "workflow_states_legacy_v1"


def ensure_workflow_state_schema(connection: SupportsMigration) -> None:
    """Create or migrate the workflow-state schema when it is missing or outdated."""

    ensure_schema(
        connection,
        name=WORKFLOW_STATE_SCHEMA_NAME,
        target_version=WORKFLOW_STATE_SCHEMA_VERSION,
        apply_schema=_apply_workflow_state_schema,
    )


def _apply_workflow_state_schema(connection: SupportsMigration) -> None:
    connection.executescript(WORKFLOW_STATE_SCHEMA)

    legacy_source_table = _resolve_legacy_source_table(connection)
    if legacy_source_table is None:
        return

    _migrate_legacy_rows(connection, source_table=legacy_source_table)


def _resolve_legacy_source_table(connection: SupportsMigration) -> str | None:
    if table_exists(connection, name=LEGACY_WORKFLOW_STATE_BACKUP_TABLE):
        return LEGACY_WORKFLOW_STATE_BACKUP_TABLE

    if not table_exists(connection, name=LEGACY_WORKFLOW_STATE_TABLE):
        return None

    connection.execute(
        f"ALTER TABLE {LEGACY_WORKFLOW_STATE_TABLE} RENAME TO {LEGACY_WORKFLOW_STATE_BACKUP_TABLE}"
    )
    return LEGACY_WORKFLOW_STATE_BACKUP_TABLE


def _migrate_legacy_rows(connection: SupportsMigration, *, source_table: str) -> None:
    rows = connection.execute(
        (
            "SELECT session_id, state_json, metadata_json, version, created_at, updated_at "
            f"FROM {source_table}"
        )
    ).fetchall()

    for row in rows:
        session_id, state_json, metadata_json, version, created_at, updated_at = row
        payload = _decode_legacy_json_object(
            state_json,
            field_name="state_json",
            session_id=session_id,
        )
        metadata = _decode_legacy_json_object(
            metadata_json,
            field_name="metadata_json",
            session_id=session_id,
        )
        state_version = _decode_legacy_int(
            version,
            field_name="version",
            session_id=session_id,
        )

        canonical_state_json = dumps_canonical_json(payload)
        state_size_bytes = len(canonical_state_json.encode("utf-8"))
        state_hash = hash_canonical_json(payload)
        message_count = extract_message_count(payload)
        current_step = extract_current_step(payload)
        checkpoint_name = extract_checkpoint_name(payload)
        user_id, user_id_hash, usecase = _extract_legacy_session_columns(metadata)

        connection.execute(
            """
            INSERT INTO workflow_sessions (
                session_id,
                user_id,
                user_id_hash,
                usecase,
                status,
                created_at,
                updated_at,
                last_activity_at,
                reset_count,
                metadata_json
            )
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?, 0, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id = COALESCE(excluded.user_id, workflow_sessions.user_id),
                user_id_hash = COALESCE(excluded.user_id_hash, workflow_sessions.user_id_hash),
                usecase = COALESCE(excluded.usecase, workflow_sessions.usecase),
                status = 'active',
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_activity_at = excluded.last_activity_at,
                metadata_json = excluded.metadata_json
            """,
            (
                session_id,
                user_id,
                user_id_hash,
                usecase,
                created_at,
                updated_at,
                updated_at,
                dumps_canonical_json(metadata),
            ),
        )
        connection.execute(
            """
            INSERT INTO workflow_state_current (
                session_id,
                state_version,
                state_json,
                state_hash,
                state_size_bytes,
                message_count,
                current_step,
                checkpoint_name,
                created_at,
                updated_at,
                reset_generation
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(session_id) DO UPDATE SET
                state_version = excluded.state_version,
                state_json = excluded.state_json,
                state_hash = excluded.state_hash,
                state_size_bytes = excluded.state_size_bytes,
                message_count = excluded.message_count,
                current_step = excluded.current_step,
                checkpoint_name = excluded.checkpoint_name,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                reset_generation = excluded.reset_generation
            """,
            (
                session_id,
                state_version,
                canonical_state_json,
                state_hash,
                state_size_bytes,
                message_count,
                current_step,
                checkpoint_name,
                created_at,
                updated_at,
            ),
        )


def _decode_legacy_json_object(
    value: object,
    *,
    field_name: str,
    session_id: object,
) -> dict[str, Any]:
    if not isinstance(value, str):
        raise WorkflowStateMigrationError(
            f"Legacy workflow-state {field_name} is not valid text for session {session_id!r}."
        )

    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkflowStateMigrationError(
            f"Legacy workflow-state {field_name} contains invalid JSON for session {session_id!r}."
        ) from exc

    if not isinstance(payload, dict):
        raise WorkflowStateMigrationError(
            f"Legacy workflow-state {field_name} must decode to a JSON object for session {session_id!r}."
        )

    return cast(dict[str, Any], payload)


def _decode_legacy_int(
    value: object,
    *,
    field_name: str,
    session_id: object,
) -> int:
    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, (float, str)):
        try:
            return int(value)
        except ValueError as exc:
            raise WorkflowStateMigrationError(
                f"Legacy workflow-state {field_name} is not a valid integer for session {session_id!r}."
            ) from exc

    raise WorkflowStateMigrationError(
        f"Legacy workflow-state {field_name} is not a valid integer for session {session_id!r}."
    )


def _extract_legacy_session_columns(
    metadata: Mapping[str, object],
) -> tuple[str | None, str | None, str | None]:
    user_id = metadata.get("user_id")
    user_id_hash = metadata.get("user_id_hash")
    usecase = metadata.get("usecase")
    return (
        user_id if isinstance(user_id, str) else None,
        user_id_hash if isinstance(user_id_hash, str) else None,
        usecase if isinstance(usecase, str) else None,
    )