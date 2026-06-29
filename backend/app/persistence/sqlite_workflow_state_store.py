"""SQLite-backed workflow-state store implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from typing import Any, Protocol, cast
from uuid import uuid4

from app.contracts.health import HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_OK
from app.contracts.state import (
    WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW,
    WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
    WorkflowSessionDeleteResult,
    WorkflowSessionListResult,
    WorkflowSessionSummary,
    WorkflowStateRecord,
    WorkflowStateResetResult,
    WorkflowStateSaveResult,
    default_workflow_state,
    normalize_workflow_state_session_id,
)
from app.persistence.errors import (
    PersistenceConfigurationError,
    PersistenceSerializationError,
    PersistenceUnavailableError,
    WorkflowStateConflictError,
    WorkflowStateConfigurationError,
    WorkflowStateError,
    WorkflowStateMigrationError,
    WorkflowStateSerializationError,
    WorkflowStateSizeError,
    WorkflowStateUnavailableError,
)
from app.persistence.serialization import (
    dumps_canonical_json,
    extract_checkpoint_name,
    extract_current_step,
    extract_message_count,
    hash_canonical_json,
    to_jsonable,
)
from app.persistence.settings import SqliteWorkflowStateSettings
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite.migrations import get_schema_version
from app.persistence.sqlite_workflow_state_schema import (
    WORKFLOW_STATE_SCHEMA_NAME,
    WORKFLOW_STATE_SCHEMA_VERSION,
    ensure_workflow_state_schema,
)

_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "authorization",
        "auth",
        "bearer",
        "cookie",
        "credential",
        "credentials",
        "jwt",
        "password",
        "secret",
        "token",
    }
)
_SENSITIVE_KEY_COMBINATIONS = (
    ("api", "key"),
    ("client", "secret"),
    ("connection", "string"),
    ("refresh", "token"),
    ("private", "key"),
    ("access", "token"),
)
_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
_CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True, slots=True)
class _PreparedWorkflowState:
    state: dict[str, Any]
    state_json: str
    state_hash: str
    state_size_bytes: int
    message_count: int
    current_step: str | None
    checkpoint_name: str | None


@dataclass(frozen=True, slots=True)
class _LoadedWorkflowState:
    state: dict[str, Any]
    found: bool
    state_version: int | None
    message_count: int
    loaded_empty: bool
    created_at: datetime | None
    updated_at: datetime | None
    reset_generation: int


@dataclass(frozen=True, slots=True)
class _SavedWorkflowState:
    session_id: str
    state: dict[str, Any]
    state_version: int
    state_size_bytes: int
    message_count: int
    reset_generation: int


@dataclass(frozen=True, slots=True)
class _ResetWorkflowState:
    session_id: str
    state_version: int | None
    reset_generation: int
    cleared_state_version: int | None
    state: dict[str, Any] | None
    deleted: bool


@dataclass(frozen=True, slots=True)
class _WorkflowSessionUpsertFields:
    user_id: str | None
    user_id_hash: str | None
    usecase: str | None


class _WorkflowStateObserver(Protocol):
    async def record_load(
        self,
        *,
        session_id: str | None,
        found: bool,
        state_version: int | None,
        history_message_count: int,
        duration_ms: int,
    ) -> None:
        ...

    async def record_save(
        self,
        *,
        session_id: str | None,
        state_version: int,
        state_size_bytes: int,
        history_message_count: int,
        duration_ms: int,
    ) -> None:
        ...

    async def record_reset(
        self,
        *,
        session_id: str | None,
        reset_generation: int,
        cleared_state_version: int | None,
        duration_ms: int,
    ) -> None:
        ...

    async def record_failure(
        self,
        *,
        operation: str,
        session_id: str | None,
        error: Exception,
        duration_ms: int,
    ) -> None:
        ...

    async def record_conflict(
        self,
        *,
        operation: str,
        session_id: str | None,
        error: Exception,
        duration_ms: int,
    ) -> None:
        ...


class SqliteWorkflowStateStore:
    """Persist one short-term workflow-state record per session."""

    def __init__(
        self,
        database_path: Path,
        *,
        settings: SqliteWorkflowStateSettings | None = None,
        observer: _WorkflowStateObserver | None = None,
    ) -> None:
        self._database_path = database_path
        self._settings = settings or SqliteWorkflowStateSettings(
            path=database_path,
            create_parent_dirs=True,
            initialize_schema=True,
            journal_mode="WAL",
            synchronous="NORMAL",
            busy_timeout_ms=5000,
            foreign_keys=True,
            required=True,
            max_state_bytes=1048576,
            max_history_messages=50,
            reset_mode=WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
            store_user_id=False,
            store_user_id_hash=True,
        )
        self._observer = observer

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def settings(self) -> SqliteWorkflowStateSettings:
        return self._settings

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def load(self, session_id: str) -> WorkflowStateRecord:
        observer_session_id = _observer_session_id(session_id)
        started_at = perf_counter()

        try:
            loaded = await asyncio.to_thread(self._load_sync, session_id)
        except WorkflowStateConflictError as exc:
            await self._record_conflict(
                operation="load",
                session_id=observer_session_id,
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise
        except Exception as exc:
            await self._record_failure(
                operation="load",
                session_id=observer_session_id,
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise

        await self._record_load(
            session_id=observer_session_id,
            found=loaded.found,
            state_version=loaded.state_version,
            history_message_count=loaded.message_count,
            duration_ms=_elapsed_ms(started_at),
        )
        return WorkflowStateRecord(
            session_id=_normalize_session_id(session_id),
            state=loaded.state,
            version=loaded.state_version,
            found=loaded.found,
            loaded_empty=loaded.loaded_empty,
            message_count=loaded.message_count,
            reset_generation=loaded.reset_generation,
            created_at=loaded.created_at,
            updated_at=loaded.updated_at,
        )

    async def save(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        expected_version: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowStateSaveResult:
        observer_session_id = _observer_session_id(session_id)
        started_at = perf_counter()

        try:
            saved = await asyncio.to_thread(
                self._save_sync,
                session_id,
                state,
                expected_version,
                dict(metadata or {}),
            )
        except WorkflowStateConflictError as exc:
            await self._record_conflict(
                operation="save",
                session_id=observer_session_id,
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise
        except Exception as exc:
            await self._record_failure(
                operation="save",
                session_id=observer_session_id,
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise

        await self._record_save(
            session_id=observer_session_id,
            state_version=saved.state_version,
            state_size_bytes=saved.state_size_bytes,
            history_message_count=saved.message_count,
            duration_ms=_elapsed_ms(started_at),
        )
        return WorkflowStateSaveResult(
            session_id=saved.session_id,
            state=saved.state,
            version=saved.state_version,
            state_size_bytes=saved.state_size_bytes,
            message_count=saved.message_count,
            reset_generation=saved.reset_generation,
        )

    async def reset(
        self,
        session_id: str,
        *,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowStateResetResult:
        observer_session_id = _observer_session_id(session_id)
        started_at = perf_counter()

        try:
            reset_result = await asyncio.to_thread(
                self._reset_sync,
                session_id,
                reason,
                dict(metadata or {}),
            )
        except WorkflowStateConflictError as exc:
            await self._record_conflict(
                operation="reset",
                session_id=observer_session_id,
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise
        except Exception as exc:
            await self._record_failure(
                operation="reset",
                session_id=observer_session_id,
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise

        await self._record_reset(
            session_id=observer_session_id,
            reset_generation=reset_result.reset_generation,
            cleared_state_version=reset_result.cleared_state_version,
            duration_ms=_elapsed_ms(started_at),
        )
        return WorkflowStateResetResult(
            session_id=reset_result.session_id,
            version=reset_result.state_version,
            reset_generation=reset_result.reset_generation,
            cleared_version=reset_result.cleared_state_version,
            state=reset_result.state,
            deleted=reset_result.deleted,
        )

    async def list_sessions(self, *, limit: int) -> WorkflowSessionListResult:
        normalized_limit = _normalize_session_list_limit(limit)
        return await asyncio.to_thread(self._list_sessions_sync, normalized_limit)

    async def delete_session(self, session_id: str) -> WorkflowSessionDeleteResult:
        return await asyncio.to_thread(self._delete_session_sync, session_id)

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._health_sync)

    def _initialize_sync(self) -> None:
        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                if self._settings.initialize_schema:
                    ensure_workflow_state_schema(connection)
                _ensure_expected_workflow_state_schema(connection)
                connection.commit()
        except PersistenceConfigurationError as exc:
            raise WorkflowStateConfigurationError(
                "Workflow-state store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise WorkflowStateUnavailableError(
                "Workflow-state store initialization failed."
            ) from exc
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError("Workflow-state store initialization failed.") from exc

    def _load_sync(self, session_id: str) -> _LoadedWorkflowState:
        normalized_session_id = _normalize_session_id(session_id)

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                row = cast(
                    tuple[str, int, int, str, str, int] | None,
                    connection.execute(
                        """
                        SELECT state_json, state_version, message_count, created_at, updated_at, reset_generation
                        FROM workflow_state_current
                        WHERE session_id = ?
                        """,
                        (normalized_session_id,),
                    ).fetchone(),
                )
                session_row = None
                if row is None:
                    session_row = cast(
                        tuple[int] | None,
                        connection.execute(
                            "SELECT reset_count FROM workflow_sessions WHERE session_id = ?",
                            (normalized_session_id,),
                        ).fetchone(),
                    )
        except PersistenceConfigurationError as exc:
            raise WorkflowStateConfigurationError(
                "Workflow-state store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise WorkflowStateUnavailableError("Workflow-state load failed.") from exc

        if row is None:
            return _LoadedWorkflowState(
                state=default_workflow_state(normalized_session_id),
                found=False,
                state_version=None,
                message_count=0,
                loaded_empty=True,
                created_at=None,
                updated_at=None,
                reset_generation=(int(session_row[0]) if session_row is not None else 0),
            )

        try:
            payload = json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise WorkflowStateSerializationError(
                "Stored workflow-state payload is invalid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise WorkflowStateSerializationError(
                "Stored workflow-state payload must be a JSON object."
            )

        state = cast(dict[str, Any], payload)
        metadata = state.get("metadata")

        return _LoadedWorkflowState(
            state=state,
            found=True,
            state_version=int(row[1]),
            message_count=int(row[2]),
            loaded_empty=isinstance(metadata, dict) and bool(metadata.get("loaded_empty", False)),
            created_at=_parse_datetime(row[3]),
            updated_at=_parse_datetime(row[4]),
            reset_generation=int(row[5]),
        )

    def _save_sync(
        self,
        session_id: str,
        state: dict[str, Any],
        expected_version: int | None,
        metadata: dict[str, Any],
    ) -> _SavedWorkflowState:
        normalized_session_id = _normalize_session_id(session_id)
        timestamp = datetime.now(UTC).isoformat()
        session_fields = _extract_workflow_session_fields(metadata, settings=self._settings)

        try:
            prepared = self._prepare_state_for_storage(state, operation="save")
        except PersistenceSerializationError as exc:
            raise WorkflowStateSerializationError(
                "Workflow-state payload serialization failed."
            ) from exc

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                connection.execute("BEGIN IMMEDIATE")
                current_row = cast(
                    tuple[int, int] | None,
                    connection.execute(
                        "SELECT state_version, reset_generation FROM workflow_state_current WHERE session_id = ?",
                        (normalized_session_id,),
                    ).fetchone(),
                )
                current_version = int(current_row[0]) if current_row is not None else None
                if expected_version is not None and current_version != expected_version:
                    raise WorkflowStateConflictError(
                        "Workflow-state save conflicted with the current version.",
                        details={
                            "session_id": normalized_session_id,
                            "expected_version": expected_version,
                            "actual_version": current_version,
                        },
                    )

                _upsert_workflow_session(
                    connection,
                    session_id=normalized_session_id,
                    timestamp=timestamp,
                    user_id=session_fields.user_id,
                    user_id_hash=session_fields.user_id_hash,
                    usecase=session_fields.usecase,
                )
                session_row = cast(
                    tuple[int] | None,
                    connection.execute(
                        "SELECT reset_count FROM workflow_sessions WHERE session_id = ?",
                        (normalized_session_id,),
                    ).fetchone(),
                )
                reset_generation = int(session_row[0]) if session_row is not None else 0

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
                    VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        state_version = workflow_state_current.state_version + 1,
                        state_json = excluded.state_json,
                        state_hash = excluded.state_hash,
                        state_size_bytes = excluded.state_size_bytes,
                        message_count = excluded.message_count,
                        current_step = excluded.current_step,
                        checkpoint_name = excluded.checkpoint_name,
                        updated_at = excluded.updated_at,
                        reset_generation = excluded.reset_generation
                    """,
                    (
                        normalized_session_id,
                        prepared.state_json,
                        prepared.state_hash,
                        prepared.state_size_bytes,
                        prepared.message_count,
                        prepared.current_step,
                        prepared.checkpoint_name,
                        timestamp,
                        timestamp,
                        reset_generation,
                    ),
                )
                current_row = cast(
                    tuple[int, int] | None,
                    connection.execute(
                        "SELECT state_version, reset_generation FROM workflow_state_current WHERE session_id = ?",
                        (normalized_session_id,),
                    ).fetchone(),
                )
                if current_row is None:
                    raise WorkflowStateConflictError(
                        "Workflow-state save did not persist the current session row."
                    )
                connection.commit()
        except PersistenceConfigurationError as exc:
            raise WorkflowStateConfigurationError(
                "Workflow-state store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise WorkflowStateUnavailableError("Workflow-state save failed.") from exc

        return _SavedWorkflowState(
            session_id=normalized_session_id,
            state=prepared.state,
            state_version=int(current_row[0]),
            state_size_bytes=prepared.state_size_bytes,
            message_count=prepared.message_count,
            reset_generation=int(current_row[1]),
        )

    def _reset_sync(
        self,
        session_id: str,
        reason: str | None,
        metadata: dict[str, Any],
    ) -> _ResetWorkflowState:
        normalized_session_id = _normalize_session_id(session_id)
        now = datetime.now(UTC)
        timestamp = now.isoformat()
        state_version: int | None = None
        session_fields = _extract_workflow_session_fields(metadata, settings=self._settings)
        empty_state = None
        trace_id = _coerce_optional_text(metadata.get("trace_id"))
        if self._settings.reset_mode != WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW:
            empty_state = self._prepare_state_for_storage(
                default_workflow_state(normalized_session_id, now=now),
                operation="reset",
            )

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                _upsert_workflow_session(
                    connection,
                    session_id=normalized_session_id,
                    timestamp=timestamp,
                    user_id=session_fields.user_id,
                    user_id_hash=session_fields.user_id_hash,
                    usecase=session_fields.usecase,
                )
                session_row = cast(
                    tuple[int] | None,
                    connection.execute(
                        "SELECT reset_count FROM workflow_sessions WHERE session_id = ?",
                        (normalized_session_id,),
                    ).fetchone(),
                )
                current_row = cast(
                    tuple[int] | None,
                    connection.execute(
                        "SELECT state_version FROM workflow_state_current WHERE session_id = ?",
                        (normalized_session_id,),
                    ).fetchone(),
                )
                next_reset_generation = int(session_row[0]) + 1 if session_row is not None else 1
                cleared_state_version = int(current_row[0]) if current_row is not None else None

                connection.execute(
                    """
                    UPDATE workflow_sessions
                    SET
                        status = 'active',
                        reset_count = ?,
                        updated_at = ?,
                        last_activity_at = ?
                    WHERE session_id = ?
                    """,
                    (
                        next_reset_generation,
                        timestamp,
                        timestamp,
                        normalized_session_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workflow_state_resets (
                        reset_id,
                        session_id,
                        trace_id,
                        reason,
                        reset_generation,
                        cleared_state_version,
                        reset_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        normalized_session_id,
                        trace_id,
                        reason,
                        next_reset_generation,
                        cleared_state_version,
                        timestamp,
                    ),
                )

                if self._settings.reset_mode == WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW:
                    connection.execute(
                        "DELETE FROM workflow_state_current WHERE session_id = ?",
                        (normalized_session_id,),
                    )
                else:
                    if empty_state is None:
                        raise WorkflowStateConflictError(
                            "Workflow-state reset could not prepare the default state payload."
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
                        VALUES (?, 1, ?, ?, ?, 0, NULL, NULL, ?, ?, ?)
                        ON CONFLICT(session_id) DO UPDATE SET
                            state_version = workflow_state_current.state_version + 1,
                            state_json = excluded.state_json,
                            state_hash = excluded.state_hash,
                            state_size_bytes = excluded.state_size_bytes,
                            message_count = 0,
                            current_step = NULL,
                            checkpoint_name = NULL,
                            updated_at = excluded.updated_at,
                            reset_generation = excluded.reset_generation
                        """,
                        (
                            normalized_session_id,
                            empty_state.state_json,
                            empty_state.state_hash,
                            empty_state.state_size_bytes,
                            timestamp,
                            timestamp,
                            next_reset_generation,
                        ),
                    )
                    new_state_row = cast(
                        tuple[int] | None,
                        connection.execute(
                            "SELECT state_version FROM workflow_state_current WHERE session_id = ?",
                            (normalized_session_id,),
                        ).fetchone(),
                    )
                    if new_state_row is None:
                        raise WorkflowStateConflictError(
                            "Workflow-state reset did not persist the default session row."
                        )
                    state_version = int(new_state_row[0])
                if self._settings.reset_mode == WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW:
                    state_version = None

                connection.commit()
        except PersistenceConfigurationError as exc:
            raise WorkflowStateConfigurationError(
                "Workflow-state store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise WorkflowStateUnavailableError("Workflow-state reset failed.") from exc

        return _ResetWorkflowState(
            session_id=normalized_session_id,
            state_version=state_version,
            reset_generation=next_reset_generation,
            cleared_state_version=cleared_state_version,
            state=(None if empty_state is None else empty_state.state),
            deleted=self._settings.reset_mode == WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW,
        )

    def _list_sessions_sync(self, limit: int) -> WorkflowSessionListResult:
        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                rows = cast(
                    list[tuple[str, str | None, str, str, str, str, int, int]],
                    connection.execute(
                        """
                        SELECT
                            workflow_sessions.session_id,
                            workflow_sessions.usecase,
                            workflow_sessions.status,
                            workflow_sessions.created_at,
                            workflow_sessions.updated_at,
                            workflow_sessions.last_activity_at,
                            workflow_sessions.reset_count,
                            COALESCE(workflow_state_current.message_count, 0)
                        FROM workflow_sessions
                        LEFT JOIN workflow_state_current
                            ON workflow_state_current.session_id = workflow_sessions.session_id
                        ORDER BY workflow_sessions.last_activity_at DESC, workflow_sessions.session_id ASC
                        LIMIT ?
                        """,
                        (limit + 1,),
                    ).fetchall(),
                )
        except PersistenceConfigurationError as exc:
            raise WorkflowStateConfigurationError(
                "Workflow-state store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise WorkflowStateUnavailableError("Workflow-state session list failed.") from exc

        has_more = len(rows) > limit
        summaries = [
            WorkflowSessionSummary(
                session_id=row[0],
                usecase=_coerce_optional_text(row[1]),
                status=_coerce_optional_text(row[2]) or "unknown",
                created_at=_parse_datetime(row[3]),
                updated_at=_parse_datetime(row[4]),
                last_activity_at=_parse_datetime(row[5]),
                reset_count=int(row[6]),
                message_count=int(row[7]),
            )
            for row in rows[:limit]
        ]
        return WorkflowSessionListResult(
            sessions=summaries,
            limit=limit,
            has_more=has_more,
        )

    def _delete_session_sync(self, session_id: str) -> WorkflowSessionDeleteResult:
        normalized_session_id = _normalize_session_id(session_id)

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM workflow_sessions WHERE session_id = ?",
                    (normalized_session_id,),
                )
                deleted = cursor.rowcount > 0
                connection.commit()
        except PersistenceConfigurationError as exc:
            raise WorkflowStateConfigurationError(
                "Workflow-state store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise WorkflowStateUnavailableError("Workflow-state session delete failed.") from exc

        return WorkflowSessionDeleteResult(
            session_id=normalized_session_id,
            deleted=deleted,
        )

    def _health_sync(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "configured": True,
            "provider": "sqlite",
            "required": self._settings.required,
            "database_exists": self._database_path.exists(),
            "journal_mode": self._settings.journal_mode.lower(),
            "synchronous": self._settings.synchronous.lower(),
        }

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                connection.execute("SELECT 1")
                schema_version = _get_workflow_state_schema_version(connection)
        except PersistenceConfigurationError as exc:
            return {
                **payload,
                "status": self._problem_status(),
                "reason": "configuration_invalid",
                "error_type": type(exc).__name__,
            }
        except PersistenceUnavailableError as exc:
            return {
                **payload,
                "status": self._problem_status(),
                "reason": "database_unavailable",
                "error_type": type(exc).__name__,
            }
        except WorkflowStateMigrationError as exc:
            return {
                **payload,
                "status": self._problem_status(),
                "reason": "schema_validation_failed",
                "error_type": type(exc).__name__,
            }

        payload["schema_initialized"] = schema_version is not None
        payload["schema_version"] = schema_version
        if schema_version is None:
            return {
                **payload,
                "status": self._problem_status(),
                "reason": "schema_not_initialized",
            }

        if schema_version != WORKFLOW_STATE_SCHEMA_VERSION:
            return {
                **payload,
                "status": self._problem_status(),
                "reason": "schema_version_mismatch",
                "expected_schema_version": WORKFLOW_STATE_SCHEMA_VERSION,
            }

        return {
            **payload,
            "status": HEALTH_OK,
        }

    def _prepare_state_for_storage(
        self,
        state: object,
        *,
        operation: str,
    ) -> _PreparedWorkflowState:
        if not isinstance(state, dict):
            raise WorkflowStateSerializationError(
                "Workflow-state payload must be a JSON object.",
                details={"operation": operation},
            )

        normalized_state = to_jsonable(state)
        if not isinstance(normalized_state, dict):
            raise WorkflowStateSerializationError(
                "Workflow-state payload must be a JSON object.",
                details={"operation": operation},
            )

        _ensure_safe_workflow_state(normalized_state, operation=operation)
        state_json = dumps_canonical_json(normalized_state)
        state_size_bytes = len(state_json.encode("utf-8"))
        if state_size_bytes > self._settings.max_state_bytes:
            raise WorkflowStateSizeError(
                "Workflow-state payload exceeds the configured size limit.",
                details={
                    "operation": operation,
                    "state_size_bytes": state_size_bytes,
                    "max_state_bytes": self._settings.max_state_bytes,
                },
            )

        return _PreparedWorkflowState(
            state=normalized_state,
            state_json=state_json,
            state_hash=hash_canonical_json(normalized_state),
            state_size_bytes=state_size_bytes,
            message_count=extract_message_count(normalized_state),
            current_step=extract_current_step(normalized_state),
            checkpoint_name=extract_checkpoint_name(normalized_state),
        )

    def _problem_status(self) -> str:
        return HEALTH_FAILED if self._settings.required else HEALTH_DEGRADED

    async def _record_load(
        self,
        *,
        session_id: str | None,
        found: bool,
        state_version: int | None,
        history_message_count: int,
        duration_ms: int,
    ) -> None:
        if self._observer is None:
            return

        await self._observer.record_load(
            session_id=session_id,
            found=found,
            state_version=state_version,
            history_message_count=history_message_count,
            duration_ms=duration_ms,
        )

    async def _record_save(
        self,
        *,
        session_id: str | None,
        state_version: int,
        state_size_bytes: int,
        history_message_count: int,
        duration_ms: int,
    ) -> None:
        if self._observer is None:
            return

        await self._observer.record_save(
            session_id=session_id,
            state_version=state_version,
            state_size_bytes=state_size_bytes,
            history_message_count=history_message_count,
            duration_ms=duration_ms,
        )

    async def _record_reset(
        self,
        *,
        session_id: str | None,
        reset_generation: int,
        cleared_state_version: int | None,
        duration_ms: int,
    ) -> None:
        if self._observer is None:
            return

        await self._observer.record_reset(
            session_id=session_id,
            reset_generation=reset_generation,
            cleared_state_version=cleared_state_version,
            duration_ms=duration_ms,
        )

    async def _record_failure(
        self,
        *,
        operation: str,
        session_id: str | None,
        error: Exception,
        duration_ms: int,
    ) -> None:
        if self._observer is None:
            return

        await self._observer.record_failure(
            operation=operation,
            session_id=session_id,
            error=error,
            duration_ms=duration_ms,
        )

    async def _record_conflict(
        self,
        *,
        operation: str,
        session_id: str | None,
        error: Exception,
        duration_ms: int,
    ) -> None:
        if self._observer is None:
            return

        await self._observer.record_conflict(
            operation=operation,
            session_id=session_id,
            error=error,
            duration_ms=duration_ms,
        )


def _upsert_workflow_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    timestamp: str,
    user_id: str | None,
    user_id_hash: str | None,
    usecase: str | None,
) -> None:
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
            metadata_json
        )
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?, '{}')
        ON CONFLICT(session_id) DO UPDATE SET
            user_id = COALESCE(excluded.user_id, workflow_sessions.user_id),
            user_id_hash = COALESCE(excluded.user_id_hash, workflow_sessions.user_id_hash),
            usecase = COALESCE(excluded.usecase, workflow_sessions.usecase),
            status = 'active',
            updated_at = excluded.updated_at,
            last_activity_at = excluded.last_activity_at,
            metadata_json = CASE
                WHEN excluded.metadata_json = '{}' THEN workflow_sessions.metadata_json
                ELSE excluded.metadata_json
            END
        """,
        (
            session_id,
            user_id,
            user_id_hash,
            usecase,
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def _normalize_session_id(session_id: object) -> str:
    try:
        return normalize_workflow_state_session_id(session_id)
    except ValueError as exc:
        raise WorkflowStateError("Invalid workflow-state session identifier.") from exc


def _observer_session_id(session_id: object) -> str | None:
    try:
        return normalize_workflow_state_session_id(session_id)
    except ValueError:
        return None


def _elapsed_ms(started_at: float) -> int:
    return max(int((perf_counter() - started_at) * 1000), 0)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or value.strip() == "":
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _coerce_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def _normalize_session_list_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise WorkflowStateError("Workflow-state session list limit must be a positive integer.")

    return limit


def _extract_workflow_session_fields(
    metadata: Mapping[str, Any],
    *,
    settings: SqliteWorkflowStateSettings,
) -> _WorkflowSessionUpsertFields:
    return _WorkflowSessionUpsertFields(
        user_id=(
            _coerce_optional_text(metadata.get("user_id"))
            if settings.store_user_id
            else None
        ),
        user_id_hash=(
            _coerce_optional_text(metadata.get("user_id_hash"))
            if settings.store_user_id_hash
            else None
        ),
        usecase=_coerce_optional_text(metadata.get("usecase")),
    )


def _get_workflow_state_schema_version(connection: sqlite3.Connection) -> int | None:
    try:
        return get_schema_version(connection, name=WORKFLOW_STATE_SCHEMA_NAME)
    except TypeError as exc:
        raise WorkflowStateMigrationError(
            "Workflow-state schema version metadata is invalid."
        ) from exc


def _ensure_expected_workflow_state_schema(connection: sqlite3.Connection) -> None:
    schema_version = _get_workflow_state_schema_version(connection)
    if schema_version != WORKFLOW_STATE_SCHEMA_VERSION:
        raise WorkflowStateMigrationError(
            "Workflow-state schema version is unsupported.",
            details={
                "expected_schema_version": WORKFLOW_STATE_SCHEMA_VERSION,
                "actual_schema_version": schema_version,
            },
        )


def _ensure_safe_workflow_state(state: dict[str, Any], *, operation: str) -> None:
    for path, key in _iter_sensitive_key_paths(state):
        raise WorkflowStateSerializationError(
            "Workflow-state payload contains sensitive field names.",
            details={
                "operation": operation,
                "field_path": path,
                "field_name": key,
            },
        )


def _iter_sensitive_key_paths(state: dict[str, Any]) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []

    def walk(value: object, *, path: str) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = f"{path}.{key}" if path else key
                if _workflow_state_key_is_sensitive(key):
                    matches.append((child_path, key))
                walk(child, path=child_path)
            return

        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path=f"{path}[{index}]")

    walk(state, path="state")
    return matches


def _workflow_state_key_is_sensitive(key: str) -> bool:
    normalized_key = _normalize_workflow_state_key(key)
    if normalized_key == "key":
        return True

    tokens = {token for token in normalized_key.split("_") if token}
    if tokens & _SENSITIVE_KEY_TOKENS:
        return True

    return any(all(part in tokens for part in combination) for combination in _SENSITIVE_KEY_COMBINATIONS)


def _normalize_workflow_state_key(key: str) -> str:
    snake_case = _CAMEL_CASE_BOUNDARY_PATTERN.sub("_", key).lower()
    normalized = _NON_ALNUM_PATTERN.sub("_", snake_case)
    return normalized.strip("_")