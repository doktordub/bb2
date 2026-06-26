"""SQLite-backed trace store implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.contracts.health import HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_OK
from app.contracts.trace import (
    TERMINAL_TRACE_STATUSES,
    TraceEvent,
    TraceReadModel,
    TraceSearchFilters,
    TraceSummary,
)
from app.persistence.errors import (
    PersistenceConfigurationError,
    PersistenceSerializationError,
    PersistenceUnavailableError,
    TraceStoreConfigurationError,
    TraceStoreError,
    TraceStoreMigrationError,
    TraceStoreNotFoundError,
    TraceStoreQueryError,
    TraceStoreRetentionError,
    TraceStoreSerializationError,
    TraceStoreUnavailableError,
    TraceStoreValidationError,
    TraceStoreWriteError,
)
from app.persistence.serialization import dumps_canonical_json, dumps_json, to_jsonable
from app.persistence.settings import SqliteTraceStoreSettings
from app.observability.ids import is_valid_trace_id
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder
from app.observability.redaction import Redactor
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite.migrations import get_schema_version
from app.persistence.sqlite_trace_queries import (
    build_read_trace_events_query,
    build_read_trace_summary_query,
    build_search_trace_summaries_query,
    normalize_trace_read_limit,
    normalize_trace_search_limit,
)
from app.persistence.sqlite_trace_schema import (
    TRACE_SCHEMA_NAME,
    TRACE_SCHEMA_VERSION,
    ensure_trace_schema,
)


class SqliteTraceStore:
    """Append-only SQLite trace-event persistence."""

    def __init__(
        self,
        database_path: Path,
        *,
        settings: SqliteTraceStoreSettings | None = None,
        metrics: MetricsRecorder | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._database_path = database_path
        self._settings = settings or SqliteTraceStoreSettings(
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
        self._redactor = Redactor(redact_secrets=True, max_chars=None)
        self._metrics = metrics or NoopMetricsRecorder()
        self._logger = logger or logging.getLogger(__name__)

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def settings(self) -> SqliteTraceStoreSettings:
        if isinstance(self._settings, SqliteTraceStoreSettings):
            return self._settings

        return SqliteTraceStoreSettings(
            path=self._settings.path,
            create_parent_dirs=self._settings.create_parent_dirs,
            initialize_schema=self._settings.initialize_schema,
            journal_mode=self._settings.journal_mode,
            synchronous=self._settings.synchronous,
            busy_timeout_ms=self._settings.busy_timeout_ms,
            foreign_keys=self._settings.foreign_keys,
            required=self._settings.required,
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

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def record_event(self, event: TraceEvent) -> None:
        await asyncio.to_thread(self._record_events_sync, (event,))

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        await asyncio.to_thread(self._record_events_sync, tuple(events))

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> TraceReadModel:
        return await asyncio.to_thread(self._read_trace_sync, trace_id, limit)

    async def search_traces(self, *, filters: TraceSearchFilters) -> list[TraceSummary]:
        return await asyncio.to_thread(self._search_traces_sync, filters)

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._health_sync)

    async def run_retention_cleanup(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._run_retention_cleanup_sync)

    def _read_trace_sync(self, trace_id: str, limit: int | None) -> TraceReadModel:
        started_at = perf_counter()
        validated_trace_id = _validate_trace_id(trace_id)

        try:
            resolved_limit = normalize_trace_read_limit(
                limit,
                max_limit=self.settings.max_events_per_trace_read,
            )
        except ValueError as exc:
            raise TraceStoreValidationError(
                "Invalid trace-store read limit.",
                details={"field_name": "limit"},
            ) from exc

        try:
            with open_sqlite_connection(self._database_path, settings=self.settings) as connection:
                _ensure_expected_trace_schema(connection)

                summary_query = build_read_trace_summary_query(trace_id=validated_trace_id)
                summary_row = connection.execute(
                    summary_query.sql,
                    summary_query.parameters,
                ).fetchone()

                if summary_row is None:
                    raise TraceStoreNotFoundError(
                        "Trace-store trace was not found.",
                        details={"trace_id": validated_trace_id},
                    )

                summary = _decode_trace_summary_row(summary_row)
                events: tuple[TraceEvent, ...]
                if resolved_limit == 0:
                    events = ()
                else:
                    events_query = build_read_trace_events_query(
                        trace_id=validated_trace_id,
                        limit=resolved_limit,
                    )
                    event_rows = connection.execute(
                        events_query.sql,
                        events_query.parameters,
                    ).fetchall()
                    events = tuple(_decode_trace_event_row(row) for row in event_rows)

                model = TraceReadModel.from_summary(summary, events=events, found=True)
                self._observe_query_success(
                    operation="read",
                    duration_ms=_elapsed_ms(started_at),
                    result_count=len(events),
                )
                return model
        except TraceStoreNotFoundError:
            self._observe_query_success(
                operation="read",
                duration_ms=_elapsed_ms(started_at),
                result_count=0,
            )
            return TraceReadModel.not_found(trace_id=validated_trace_id)
        except PersistenceUnavailableError as exc:
            self._observe_trace_failure(
                operation="read",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise TraceStoreUnavailableError("Trace store read failed.") from exc
        except TraceStoreError as exc:
            self._observe_trace_failure(
                operation="read",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise
        except Exception as exc:
            self._observe_trace_failure(
                operation="read",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise TraceStoreQueryError("Trace store read failed.") from exc

    def _search_traces_sync(self, filters: TraceSearchFilters) -> list[TraceSummary]:
        started_at = perf_counter()
        normalized_filters = _normalize_trace_search_filters(
            filters,
            max_limit=self.settings.max_search_results,
        )

        try:
            with open_sqlite_connection(self._database_path, settings=self.settings) as connection:
                _ensure_expected_trace_schema(connection)
                query = build_search_trace_summaries_query(
                    filters=normalized_filters,
                    max_limit=self.settings.max_search_results,
                )
                rows = connection.execute(query.sql, query.parameters).fetchall()
                results = [_decode_trace_summary_row(row) for row in rows]
                self._observe_query_success(
                    operation="search",
                    duration_ms=_elapsed_ms(started_at),
                    result_count=len(results),
                )
                return results
        except PersistenceUnavailableError as exc:
            self._observe_trace_failure(
                operation="search",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise TraceStoreUnavailableError("Trace store search failed.") from exc
        except TraceStoreError as exc:
            self._observe_trace_failure(
                operation="search",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise
        except Exception as exc:
            self._observe_trace_failure(
                operation="search",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            raise TraceStoreQueryError("Trace store search failed.") from exc

    def _initialize_sync(self) -> None:
        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                if self._settings.initialize_schema:
                    ensure_trace_schema(connection)
                _ensure_expected_trace_schema(connection)
                connection.commit()
        except PersistenceConfigurationError as exc:
            raise TraceStoreConfigurationError(
                "Trace store configuration is invalid."
            ) from exc
        except PersistenceUnavailableError as exc:
            raise TraceStoreUnavailableError(
                "Trace store initialization failed."
            ) from exc
        except TraceStoreError:
            raise
        except Exception as exc:
            raise TraceStoreError("Trace store initialization failed.") from exc

    def _record_events_sync(self, events: Sequence[TraceEvent]) -> None:
        started_at = perf_counter()
        if not events:
            return

        prepared_events: tuple[_PreparedTraceEvent, ...] = ()
        if len(events) > _MAX_BATCH_EVENTS:
            error = TraceStoreValidationError(
                "Trace-store batch exceeds the supported event limit.",
                details={"max_batch_events": _MAX_BATCH_EVENTS},
            )
            self._observe_trace_failure(
                operation="record",
                error=error,
                duration_ms=_elapsed_ms(started_at),
            )
            raise error

        try:
            prepared_events = tuple(self._prepare_event(event) for event in events)
            with open_sqlite_connection(self._database_path, settings=self.settings) as connection:
                connection.execute("BEGIN IMMEDIATE")

                next_sequence_by_trace: dict[str, int] = {}
                for prepared_event in prepared_events:
                    if prepared_event.trace_id not in next_sequence_by_trace:
                        next_sequence_by_trace[prepared_event.trace_id] = _next_sequence_no(
                            connection,
                            trace_id=prepared_event.trace_id,
                        )

                    sequence_no = next_sequence_by_trace[prepared_event.trace_id]
                    next_sequence_by_trace[prepared_event.trace_id] = sequence_no + 1

                    _upsert_trace_run(connection, prepared_event)
                    _insert_trace_event(connection, prepared_event, sequence_no=sequence_no)
                    _update_trace_run_counters(connection, prepared_event)

                connection.commit()
            self._observe_record_success(prepared_events, duration_ms=_elapsed_ms(started_at))
        except PersistenceUnavailableError as exc:
            self._observe_trace_failure(
                operation="record",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
                event=prepared_events[0] if len(prepared_events) == 1 else None,
            )
            raise TraceStoreUnavailableError("Trace store write failed.") from exc
        except TraceStoreError as exc:
            self._observe_trace_failure(
                operation="record",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
                event=prepared_events[0] if len(prepared_events) == 1 else None,
            )
            raise
        except Exception as exc:
            self._observe_trace_failure(
                operation="record",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
                event=prepared_events[0] if len(prepared_events) == 1 else None,
            )
            raise TraceStoreWriteError("Trace store write failed.") from exc

    def _prepare_event(self, event: TraceEvent) -> "_PreparedTraceEvent":
        settings = self.settings
        trace_id = _validate_trace_id(event.trace_id)
        event_id = _validate_optional_identifier(event.event_id, field_name="event_id") or _new_event_id()
        event_name = _validate_event_name(event.resolved_event_name, field_name="event_name")
        event_type = _validate_event_name(event.event_type, field_name="event_type")
        status = _validate_choice(event.status, field_name="status", allowed=_ALLOWED_STATUSES)
        severity = _validate_choice(event.severity, field_name="severity", allowed=_ALLOWED_SEVERITIES)
        component = _validate_component(event.component)
        timestamp = _normalize_timestamp(event.timestamp)
        timestamp_iso = timestamp.isoformat()
        parent_event_id = _validate_optional_identifier(event.parent_event_id, field_name="parent_event_id")
        parent_trace_id = _validate_optional_trace_id(event.parent_trace_id)

        raw_session_id = _normalize_optional_text(event.session_id, field_name="session_id")
        raw_user_id = _normalize_optional_text(event.user_id, field_name="user_id")
        stored_session_id = raw_session_id if settings.store_raw_session_id else None
        stored_user_id = raw_user_id if settings.store_raw_user_id else None
        session_id_hash = _resolve_hash_value(
            configured_hash=event.session_id_hash,
            raw_value=raw_session_id,
            enabled=settings.store_session_id_hash,
            field_name="session_id_hash",
        )
        user_id_hash = _resolve_hash_value(
            configured_hash=event.user_id_hash,
            raw_value=raw_user_id,
            enabled=settings.store_user_id_hash,
            field_name="user_id_hash",
        )

        usecase = _normalize_optional_text(event.usecase, field_name="usecase")
        agent_name = _normalize_optional_text(event.agent_name, field_name="agent_name")
        strategy_name = _normalize_optional_text(event.strategy_name, field_name="strategy_name")
        llm_profile = _normalize_optional_text(event.llm_profile, field_name="llm_profile")
        provider = _normalize_optional_text(event.provider, field_name="provider")
        model = _normalize_optional_text(event.model, field_name="model")
        tool_name = _normalize_optional_text(event.tool_name, field_name="tool_name")
        error_type = _normalize_optional_text(event.error_type, field_name="error_type")
        error_code = _normalize_optional_text(event.error_code, field_name="error_code")
        duration_ms = _normalize_duration_ms(event.duration_ms)
        retryable = event.retryable

        payload, payload_json, payload_size_bytes = _prepare_payload(
            redactor=self._redactor,
            payload=event.payload,
            max_event_payload_bytes=settings.max_event_payload_bytes,
            max_error_detail_bytes=settings.max_error_detail_bytes,
        )
        operation = _normalize_optional_text(payload.get("operation"), field_name="operation")
        route_template = _normalize_optional_text(
            payload.get("route_template"),
            field_name="route_template",
            max_length=256,
            pattern=_SAFE_TEXT_PATTERN,
        )
        metadata_json = dumps_canonical_json(_extract_metadata(payload))
        error_increment = 1 if _is_error_event(status=status, severity=severity) else 0
        ended_at = timestamp_iso if status in TERMINAL_TRACE_STATUSES else None

        return _PreparedTraceEvent(
            trace_id=trace_id,
            event_id=event_id,
            parent_event_id=parent_event_id,
            parent_trace_id=parent_trace_id,
            event_name=event_name,
            event_type=event_type,
            status=status,
            severity=severity,
            component=component,
            timestamp_iso=timestamp_iso,
            duration_ms=duration_ms,
            session_id=stored_session_id,
            session_id_hash=session_id_hash,
            user_id=stored_user_id,
            user_id_hash=user_id_hash,
            usecase=usecase,
            agent_name=agent_name,
            strategy_name=strategy_name,
            llm_profile=llm_profile,
            provider=provider,
            model=model,
            tool_name=tool_name,
            error_type=error_type,
            error_code=error_code,
            retryable=retryable,
            payload_json=payload_json,
            payload_size_bytes=payload_size_bytes,
            redaction_version=_TRACE_REDACTION_VERSION,
            operation=operation,
            route_template=route_template,
            metadata_json=metadata_json,
            ended_at=ended_at,
            error_increment=error_increment,
            created_at=timestamp_iso,
            updated_at=timestamp_iso,
        )

    def _health_sync(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "configured": True,
            "provider": "sqlite",
            "required": self.settings.required,
            "database_exists": self._database_path.exists(),
            "journal_mode": self.settings.journal_mode.lower(),
            "synchronous": self.settings.synchronous.lower(),
            "retention_enabled": self.settings.retention_enabled,
        }

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                connection.execute("SELECT 1")
                schema_version = _get_trace_schema_version(connection)
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
        except TraceStoreMigrationError as exc:
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

        if schema_version != TRACE_SCHEMA_VERSION:
            return {
                **payload,
                "status": self._problem_status(),
                "reason": "schema_version_mismatch",
                "expected_schema_version": TRACE_SCHEMA_VERSION,
            }

        return {
            **payload,
            "status": HEALTH_OK,
        }

    def _run_retention_cleanup_sync(self) -> dict[str, Any]:
        started_at = perf_counter()
        if not self.settings.retention_enabled:
            return {
                "status": HEALTH_OK,
                "retention_enabled": False,
                "deleted_trace_count": 0,
                "deleted_event_count": 0,
            }

        cutoff_at = datetime.now(UTC) - timedelta(days=self.settings.retention_keep_days)
        cutoff_iso = cutoff_at.isoformat()
        retention_run_id = f"ret_{uuid4().hex}"

        try:
            with open_sqlite_connection(self._database_path, settings=self.settings) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO trace_retention_runs (
                        retention_run_id,
                        started_at,
                        cutoff_at,
                        status,
                        metadata_json
                    )
                    VALUES (?, ?, ?, 'started', ?)
                    """,
                    (
                        retention_run_id,
                        datetime.now(UTC).isoformat(),
                        cutoff_iso,
                        dumps_canonical_json(
                            {
                                "cleanup_batch_size": self.settings.retention_cleanup_batch_size,
                                "keep_days": self.settings.retention_keep_days,
                            }
                        ),
                    ),
                )

                trace_ids = _select_retention_candidate_trace_ids(
                    connection,
                    cutoff_at=cutoff_iso,
                    limit=self.settings.retention_cleanup_batch_size,
                )
                deleted_event_count = _count_trace_events(connection, trace_ids=trace_ids)
                deleted_trace_count = len(trace_ids)
                if trace_ids:
                    _delete_trace_runs(connection, trace_ids=trace_ids)

                completed_at = datetime.now(UTC).isoformat()
                connection.execute(
                    """
                    UPDATE trace_retention_runs
                    SET
                        completed_at = ?,
                        deleted_trace_count = ?,
                        deleted_event_count = ?,
                        status = 'completed'
                    WHERE retention_run_id = ?
                    """,
                    (
                        completed_at,
                        deleted_trace_count,
                        deleted_event_count,
                        retention_run_id,
                    ),
                )
                connection.commit()
        except PersistenceUnavailableError as exc:
            self._observe_trace_failure(
                operation="retention",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            _record_retention_failure(
                self,
                retention_run_id=retention_run_id,
                cutoff_at=cutoff_iso,
                error=exc,
            )
            raise TraceStoreUnavailableError("Trace store retention cleanup failed.") from exc
        except TraceStoreError as exc:
            self._observe_trace_failure(
                operation="retention",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            _record_retention_failure(
                self,
                retention_run_id=retention_run_id,
                cutoff_at=cutoff_iso,
                error=exc,
            )
            raise TraceStoreRetentionError("Trace store retention cleanup failed.") from exc
        except Exception as exc:
            self._observe_trace_failure(
                operation="retention",
                error=exc,
                duration_ms=_elapsed_ms(started_at),
            )
            _record_retention_failure(
                self,
                retention_run_id=retention_run_id,
                cutoff_at=cutoff_iso,
                error=exc,
            )
            raise TraceStoreRetentionError("Trace store retention cleanup failed.") from exc

        self._observe_retention_success(
            duration_ms=_elapsed_ms(started_at),
            deleted_trace_count=deleted_trace_count,
            deleted_event_count=deleted_event_count,
        )

        return {
            "status": HEALTH_OK,
            "retention_enabled": True,
            "retention_run_id": retention_run_id,
            "cutoff_at": cutoff_iso,
            "deleted_trace_count": deleted_trace_count,
            "deleted_event_count": deleted_event_count,
        }

    def _problem_status(self) -> str:
        return HEALTH_FAILED if self.settings.required else HEALTH_DEGRADED

    def _observe_record_success(
        self,
        events: Sequence[_PreparedTraceEvent],
        *,
        duration_ms: int,
    ) -> None:
        total_payload_bytes = sum(event.payload_size_bytes for event in events)
        tags = _trace_metric_tags(
            operation="record",
            success=True,
            provider="sqlite",
            event=events[0] if len(events) == 1 else None,
        )
        self._metrics.increment("backend.trace.record.total", value=len(events), tags=tags)
        self._metrics.timing("backend.trace.record.duration_ms", duration_ms, tags=tags)
        self._metrics.increment("backend.trace.record.bytes", value=total_payload_bytes, tags=tags)
        self._logger.debug(
            "Trace store record completed",
            extra={
                "component": "persistence.trace",
                "event_type": "trace_store_record",
                "status": "ok",
                "details": {
                    "event_count": len(events),
                    "payload_bytes": total_payload_bytes,
                    "duration_ms": duration_ms,
                },
            },
        )

    def _observe_query_success(
        self,
        *,
        operation: str,
        duration_ms: int,
        result_count: int,
    ) -> None:
        tags = _trace_metric_tags(operation=operation, success=True, provider="sqlite")
        self._metrics.increment(f"backend.trace.{operation}.total", tags=tags)
        self._metrics.timing(f"backend.trace.{operation}.duration_ms", duration_ms, tags=tags)
        if operation == "search":
            self._metrics.increment("backend.trace.search.results", value=result_count, tags=tags)
        self._logger.debug(
            f"Trace store {operation} completed",
            extra={
                "component": "persistence.trace",
                "event_type": f"trace_store_{operation}",
                "status": "ok",
                "details": {
                    "duration_ms": duration_ms,
                    "result_count": result_count,
                },
            },
        )

    def _observe_retention_success(
        self,
        *,
        duration_ms: int,
        deleted_trace_count: int,
        deleted_event_count: int,
    ) -> None:
        tags = _trace_metric_tags(operation="retention", success=True, provider="sqlite")
        self._metrics.increment(
            "backend.trace.retention.deleted_traces",
            value=deleted_trace_count,
            tags=tags,
        )
        self._metrics.increment(
            "backend.trace.retention.deleted_events",
            value=deleted_event_count,
            tags=tags,
        )
        self._logger.info(
            "Trace store retention cleanup completed",
            extra={
                "component": "persistence.trace",
                "event_type": "trace_store_retention",
                "status": "ok",
                "details": {
                    "duration_ms": duration_ms,
                    "deleted_trace_count": deleted_trace_count,
                    "deleted_event_count": deleted_event_count,
                },
            },
        )

    def _observe_trace_failure(
        self,
        *,
        operation: str,
        error: Exception,
        duration_ms: int,
        event: _PreparedTraceEvent | None = None,
    ) -> None:
        tags = _trace_metric_tags(
            operation=operation,
            success=False,
            provider="sqlite",
            error_type=type(error).__name__,
            event=event,
        )
        self._metrics.increment(f"backend.trace.{operation}.errors", tags=tags)
        self._logger.error(
            f"Trace store {operation} failed",
            extra={
                "component": "persistence.trace",
                "event_type": f"trace_store_{operation}",
                "status": "error",
                "error_type": type(error).__name__,
                "details": {
                    "duration_ms": duration_ms,
                },
            },
        )


def _get_trace_schema_version(connection: sqlite3.Connection) -> int | None:
    try:
        return get_schema_version(connection, name=TRACE_SCHEMA_NAME)
    except TypeError as exc:
        raise TraceStoreMigrationError(
            "Trace-store schema version metadata is invalid."
        ) from exc


def _ensure_expected_trace_schema(connection: sqlite3.Connection) -> None:
    schema_version = _get_trace_schema_version(connection)
    if schema_version != TRACE_SCHEMA_VERSION:
        raise TraceStoreMigrationError(
            "Trace-store schema version is unsupported.",
            details={
                "expected_schema_version": TRACE_SCHEMA_VERSION,
                "actual_schema_version": schema_version,
            },
        )


@dataclass(frozen=True, slots=True)
class _PreparedTraceEvent:
    trace_id: str
    event_id: str
    parent_event_id: str | None
    parent_trace_id: str | None
    event_name: str
    event_type: str
    status: str
    severity: str
    component: str
    timestamp_iso: str
    duration_ms: float | None
    session_id: str | None
    session_id_hash: str | None
    user_id: str | None
    user_id_hash: str | None
    usecase: str | None
    agent_name: str | None
    strategy_name: str | None
    llm_profile: str | None
    provider: str | None
    model: str | None
    tool_name: str | None
    error_type: str | None
    error_code: str | None
    retryable: bool | None
    payload_json: str
    payload_size_bytes: int
    redaction_version: int
    operation: str | None
    route_template: str | None
    metadata_json: str
    ended_at: str | None
    error_increment: int
    created_at: str
    updated_at: str


_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SAFE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9_./:-]{1,256}$")
_ALLOWED_STATUSES = frozenset({"started", "completed", "failed", "cancelled", "skipped", "degraded"})
_ALLOWED_SEVERITIES = frozenset({"debug", "info", "warning", "error", "critical"})
_MAX_BATCH_EVENTS = 100
_TRACE_REDACTION_VERSION = 1
_ERROR_DETAIL_KEYS = frozenset({"details", "error", "error_detail"})


def _validate_trace_id(value: str) -> str:
    candidate = value.strip()
    if not is_valid_trace_id(candidate):
        raise TraceStoreValidationError("Invalid trace-store trace identifier.")
    return candidate


def _validate_optional_trace_id(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_trace_id(value)


def _validate_optional_identifier(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None

    candidate = value.strip()
    if not candidate or not candidate.isascii() or not _SAFE_IDENTIFIER_PATTERN.fullmatch(candidate):
        raise TraceStoreValidationError(
            f"Invalid trace-store {field_name}.",
            details={"field_name": field_name},
        )
    return candidate


def _validate_event_name(value: str, *, field_name: str) -> str:
    candidate = value.strip()
    if not candidate or not candidate.isascii() or not _SAFE_EVENT_NAME_PATTERN.fullmatch(candidate):
        raise TraceStoreValidationError(
            f"Invalid trace-store {field_name}.",
            details={"field_name": field_name},
        )
    return candidate


def _validate_choice(value: str, *, field_name: str, allowed: frozenset[str]) -> str:
    candidate = value.strip().lower()
    if candidate not in allowed:
        raise TraceStoreValidationError(
            f"Invalid trace-store {field_name}.",
            details={"field_name": field_name, "allowed": sorted(allowed)},
        )
    return candidate


def _validate_component(value: str) -> str:
    candidate = value.strip()
    if not candidate or not candidate.isascii() or not _SAFE_COMPONENT_PATTERN.fullmatch(candidate):
        raise TraceStoreValidationError("Invalid trace-store component name.")
    return candidate


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_optional_text(
    value: object,
    *,
    field_name: str,
    max_length: int = 128,
    pattern: re.Pattern[str] | None = _SAFE_IDENTIFIER_PATTERN,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TraceStoreValidationError(
            f"Invalid trace-store {field_name}.",
            details={"field_name": field_name},
        )

    candidate = value.strip()
    if candidate == "":
        return None
    if not candidate.isascii() or len(candidate) > max_length:
        raise TraceStoreValidationError(
            f"Invalid trace-store {field_name}.",
            details={"field_name": field_name},
        )
    if pattern is not None and not pattern.fullmatch(candidate):
        raise TraceStoreValidationError(
            f"Invalid trace-store {field_name}.",
            details={"field_name": field_name},
        )
    return candidate


def _normalize_duration_ms(value: float | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if normalized < 0:
        raise TraceStoreValidationError("Invalid trace-store duration_ms.")
    return normalized


def _resolve_hash_value(
    *,
    configured_hash: str | None,
    raw_value: str | None,
    enabled: bool,
    field_name: str,
) -> str | None:
    if not enabled:
        return None
    if configured_hash is not None:
        return _normalize_optional_text(configured_hash, field_name=field_name, max_length=256)
    if raw_value is None:
        return None
    return _hash_identifier(raw_value)


def _hash_identifier(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _new_event_id() -> str:
    return f"evt_{uuid4().hex}"


def _prepare_payload(
    *,
    redactor: Redactor,
    payload: object,
    max_event_payload_bytes: int,
    max_error_detail_bytes: int,
) -> tuple[dict[str, Any], str, int]:
    try:
        normalized_payload = to_jsonable(dict(payload) if isinstance(payload, dict) else payload)
        redacted = redactor.redact(normalized_payload)
    except PersistenceSerializationError as exc:
        raise TraceStoreSerializationError("Trace store payload serialization failed.") from exc
    except Exception as exc:
        raise TraceStoreSerializationError("Trace store payload serialization failed.") from exc

    if isinstance(redacted, dict):
        payload_mapping: dict[str, Any] = dict(redacted)
    else:
        payload_mapping = {"value": redacted}

    payload_mapping = _bound_error_details(payload_mapping, max_error_detail_bytes=max_error_detail_bytes)
    payload_mapping, payload_json, payload_size_bytes = _bound_payload_size(
        payload_mapping,
        max_event_payload_bytes=max_event_payload_bytes,
    )
    return payload_mapping, payload_json, payload_size_bytes


def _bound_error_details(
    payload: dict[str, Any],
    *,
    max_error_detail_bytes: int,
) -> dict[str, Any]:
    bounded = dict(payload)
    for key in tuple(bounded.keys()):
        if key not in _ERROR_DETAIL_KEYS:
            continue
        try:
            detail_json = dumps_json(bounded[key])
        except PersistenceSerializationError:
            bounded[key] = {"truncated": True, "reason": "serialization_failed"}
            continue

        detail_size = len(detail_json.encode("utf-8"))
        if detail_size <= max_error_detail_bytes:
            continue
        bounded[key] = {
            "truncated": True,
            "original_size_bytes": detail_size,
            "max_size_bytes": max_error_detail_bytes,
        }
    return bounded


def _bound_payload_size(
    payload: dict[str, Any],
    *,
    max_event_payload_bytes: int,
) -> tuple[dict[str, Any], str, int]:
    try:
        payload_json = dumps_json(to_jsonable(payload))
    except PersistenceSerializationError as exc:
        raise TraceStoreSerializationError("Trace store payload serialization failed.") from exc

    payload_size = len(payload_json.encode("utf-8"))
    if payload_size <= max_event_payload_bytes:
        return payload, payload_json, payload_size

    summarized_payload: dict[str, Any] = {
        "truncated": True,
        "original_size_bytes": payload_size,
        "retained_keys": sorted(str(key) for key in payload.keys())[:20],
    }
    summary_json = dumps_json(summarized_payload)
    summary_size = len(summary_json.encode("utf-8"))
    if summary_size <= max_event_payload_bytes:
        return summarized_payload, summary_json, summary_size

    fallback_payload = {"truncated": True}
    fallback_json = dumps_json(fallback_payload)
    return fallback_payload, fallback_json, len(fallback_json.encode("utf-8"))


def _extract_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return {}


def _is_error_event(*, status: str, severity: str) -> bool:
    return status == "failed" or severity in {"error", "critical"}


def _next_sequence_no(connection: sqlite3.Connection, *, trace_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM trace_events WHERE trace_id = ?",
        (trace_id,),
    ).fetchone()
    if row is None:
        return 1
    return int(row[0])


def _upsert_trace_run(connection: sqlite3.Connection, event: _PreparedTraceEvent) -> None:
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
            last_event_at,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trace_id) DO UPDATE SET
            parent_trace_id = COALESCE(excluded.parent_trace_id, trace_runs.parent_trace_id),
            session_id = COALESCE(excluded.session_id, trace_runs.session_id),
            session_id_hash = COALESCE(excluded.session_id_hash, trace_runs.session_id_hash),
            user_id = COALESCE(excluded.user_id, trace_runs.user_id),
            user_id_hash = COALESCE(excluded.user_id_hash, trace_runs.user_id_hash),
            usecase = COALESCE(excluded.usecase, trace_runs.usecase),
            operation = COALESCE(excluded.operation, trace_runs.operation),
            route_template = COALESCE(excluded.route_template, trace_runs.route_template),
            last_event_at = excluded.last_event_at,
            status = excluded.status,
            severity = CASE
                WHEN trace_runs.severity = 'critical' OR excluded.severity = 'critical' THEN 'critical'
                WHEN trace_runs.severity = 'error' OR excluded.severity = 'error' THEN 'error'
                WHEN trace_runs.severity = 'warning' OR excluded.severity = 'warning' THEN 'warning'
                WHEN trace_runs.severity = 'info' OR excluded.severity = 'info' THEN 'info'
                ELSE excluded.severity
            END,
            agent_name = COALESCE(excluded.agent_name, trace_runs.agent_name),
            strategy_name = COALESCE(excluded.strategy_name, trace_runs.strategy_name),
            llm_profile = COALESCE(excluded.llm_profile, trace_runs.llm_profile),
            provider = COALESCE(excluded.provider, trace_runs.provider),
            model = COALESCE(excluded.model, trace_runs.model),
            tool_name = COALESCE(excluded.tool_name, trace_runs.tool_name),
            error_type = COALESCE(excluded.error_type, trace_runs.error_type),
            error_code = COALESCE(excluded.error_code, trace_runs.error_code),
            metadata_json = CASE
                WHEN excluded.metadata_json = '{}' THEN trace_runs.metadata_json
                ELSE excluded.metadata_json
            END,
            updated_at = excluded.updated_at
        """,
        (
            event.trace_id,
            event.parent_trace_id,
            event.session_id,
            event.session_id_hash,
            event.user_id,
            event.user_id_hash,
            event.usecase,
            event.operation,
            event.route_template,
            event.status,
            event.severity,
            event.timestamp_iso,
            event.timestamp_iso,
            event.agent_name,
            event.strategy_name,
            event.llm_profile,
            event.provider,
            event.model,
            event.tool_name,
            event.error_type,
            event.error_code,
            event.metadata_json,
            event.created_at,
            event.updated_at,
        ),
    )


def _insert_trace_event(
    connection: sqlite3.Connection,
    event: _PreparedTraceEvent,
    *,
    sequence_no: int,
) -> None:
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
            event.event_name,
            event.event_type,
            event.status,
            event.severity,
            event.component,
            event.timestamp_iso,
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
            event.payload_json,
            event.payload_size_bytes,
            event.redaction_version,
            event.created_at,
        ),
    )


def _update_trace_run_counters(connection: sqlite3.Connection, event: _PreparedTraceEvent) -> None:
    connection.execute(
        """
        UPDATE trace_runs
        SET
            event_count = event_count + 1,
            error_count = error_count + ?,
            ended_at = COALESCE(?, ended_at),
            duration_ms = COALESCE(?, duration_ms),
            updated_at = ?,
            status = ?,
            error_type = COALESCE(?, error_type),
            error_code = COALESCE(?, error_code)
        WHERE trace_id = ?
        """,
        (
            event.error_increment,
            event.ended_at,
            event.duration_ms,
            event.updated_at,
            event.status,
            event.error_type,
            event.error_code,
            event.trace_id,
        ),
    )


def _bool_to_sqlite(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _decode_trace_summary_row(row: sqlite3.Row | tuple[object, ...]) -> TraceSummary:
    values = tuple(row)
    metadata = _decode_json_mapping(values[23], field_name="metadata_json")
    return TraceSummary(
        trace_id=_required_text(values[0], field_name="trace_id"),
        parent_trace_id=_optional_text_value(values[1]),
        session_id_hash=_optional_text_value(values[2]),
        user_id_hash=_optional_text_value(values[3]),
        usecase=_optional_text_value(values[4]),
        operation=_optional_text_value(values[5]),
        route_template=_optional_text_value(values[6]),
        status=_optional_text_value(values[7]),
        severity=_optional_text_value(values[8]),
        started_at=_optional_timestamp(values[9], field_name="started_at"),
        ended_at=_optional_timestamp(values[10], field_name="ended_at"),
        last_event_at=_optional_timestamp(values[11], field_name="last_event_at"),
        duration_ms=_optional_float(values[12], field_name="duration_ms"),
        event_count=_required_int(values[13], field_name="event_count"),
        error_count=_required_int(values[14], field_name="error_count"),
        agent_name=_optional_text_value(values[15]),
        strategy_name=_optional_text_value(values[16]),
        llm_profile=_optional_text_value(values[17]),
        provider=_optional_text_value(values[18]),
        model=_optional_text_value(values[19]),
        tool_name=_optional_text_value(values[20]),
        error_type=_optional_text_value(values[21]),
        error_code=_optional_text_value(values[22]),
        metadata=metadata,
    )


def _decode_trace_event_row(row: sqlite3.Row | tuple[object, ...]) -> TraceEvent:
    values = tuple(row)
    payload = _decode_json_mapping(values[25], field_name="payload_json")
    return TraceEvent(
        event_id=_required_text(values[0], field_name="event_id"),
        trace_id=_required_text(values[1], field_name="trace_id"),
        session_id=_optional_text_value(values[11]) or "unknown_session",
        event_name=_required_text(values[4], field_name="event_name"),
        event_type=_required_text(values[5], field_name="event_type"),
        component=_required_text(values[8], field_name="component"),
        timestamp=_required_timestamp(values[9], field_name="timestamp"),
        status=_required_text(values[6], field_name="status"),
        severity=_required_text(values[7], field_name="severity"),
        parent_event_id=_optional_text_value(values[3]),
        session_id_hash=_optional_text_value(values[12]),
        user_id=_optional_text_value(values[13]),
        user_id_hash=_optional_text_value(values[14]),
        usecase=_optional_text_value(values[15]),
        agent_name=_optional_text_value(values[16]),
        strategy_name=_optional_text_value(values[17]),
        llm_profile=_optional_text_value(values[18]),
        provider=_optional_text_value(values[19]),
        model=_optional_text_value(values[20]),
        tool_name=_optional_text_value(values[21]),
        error_type=_optional_text_value(values[22]),
        error_code=_optional_text_value(values[23]),
        retryable=_optional_bool_from_sqlite(values[24], field_name="retryable"),
        duration_ms=_optional_float(values[10], field_name="duration_ms"),
        payload=payload,
    )


def _decode_json_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        )

    try:
        decoded = to_jsonable(json.loads(value))
    except Exception as exc:
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        ) from exc

    if isinstance(decoded, dict):
        return decoded
    return {"value": decoded}


def _required_text(value: object, *, field_name: str) -> str:
    resolved = _optional_text_value(value)
    if resolved is None:
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        )
    return resolved


def _optional_text_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _required_timestamp(value: object, *, field_name: str) -> datetime:
    resolved = _optional_timestamp(value, field_name=field_name)
    if resolved is None:
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        )
    return resolved


def _optional_timestamp(value: object, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        )

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        ) from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        )
    return value


def _optional_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TraceStoreSerializationError(
            "Trace store row decoding failed.",
            details={"field_name": field_name},
        )
    if isinstance(value, int | float):
        return float(value)
    raise TraceStoreSerializationError(
        "Trace store row decoding failed.",
        details={"field_name": field_name},
    )


def _optional_bool_from_sqlite(value: object, *, field_name: str) -> bool | None:
    if value is None:
        return None
    if value in {0, 1}:
        return bool(value)
    raise TraceStoreSerializationError(
        "Trace store row decoding failed.",
        details={"field_name": field_name},
    )


def _normalize_trace_search_filters(
    filters: TraceSearchFilters,
    *,
    max_limit: int,
) -> TraceSearchFilters:
    try:
        limit = normalize_trace_search_limit(filters.limit, max_limit=max_limit)
    except ValueError as exc:
        raise TraceStoreValidationError(
            "Invalid trace-store search limit.",
            details={"field_name": "limit"},
        ) from exc

    return TraceSearchFilters(
        started_after=_normalize_filter_timestamp(filters.started_after),
        started_before=_normalize_filter_timestamp(filters.started_before),
        status=_normalize_optional_choice(filters.status, field_name="status", allowed=_ALLOWED_STATUSES),
        severity=_normalize_optional_choice(
            filters.severity,
            field_name="severity",
            allowed=_ALLOWED_SEVERITIES,
        ),
        usecase=_normalize_optional_text(filters.usecase, field_name="usecase"),
        session_id_hash=_normalize_optional_text(
            filters.session_id_hash,
            field_name="session_id_hash",
            max_length=256,
        ),
        user_id_hash=_normalize_optional_text(
            filters.user_id_hash,
            field_name="user_id_hash",
            max_length=256,
        ),
        event_name=_normalize_optional_event_name(filters.event_name, field_name="event_name"),
        event_type=_normalize_optional_event_name(filters.event_type, field_name="event_type"),
        agent_name=_normalize_optional_text(filters.agent_name, field_name="agent_name"),
        strategy_name=_normalize_optional_text(filters.strategy_name, field_name="strategy_name"),
        llm_profile=_normalize_optional_text(filters.llm_profile, field_name="llm_profile"),
        tool_name=_normalize_optional_text(filters.tool_name, field_name="tool_name"),
        error_type=_normalize_optional_text(filters.error_type, field_name="error_type"),
        errors_only=filters.errors_only,
        limit=limit,
    )


def _normalize_filter_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _normalize_timestamp(value)


def _normalize_optional_choice(
    value: str | None,
    *,
    field_name: str,
    allowed: frozenset[str],
) -> str | None:
    if value is None:
        return None
    return _validate_choice(value, field_name=field_name, allowed=allowed)


def _normalize_optional_event_name(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _validate_event_name(value, field_name=field_name)


def _select_retention_candidate_trace_ids(
    connection: sqlite3.Connection,
    *,
    cutoff_at: str,
    limit: int,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT trace_id
        FROM trace_runs
        WHERE started_at < ?
        ORDER BY started_at ASC, trace_id ASC
        LIMIT ?
        """,
        (cutoff_at, limit),
    ).fetchall()
    return tuple(_required_text(row[0], field_name="trace_id") for row in rows)


def _count_trace_events(
    connection: sqlite3.Connection,
    *,
    trace_ids: Sequence[str],
) -> int:
    if not trace_ids:
        return 0

    placeholders = ", ".join("?" for _ in trace_ids)
    row = connection.execute(
        f"SELECT COUNT(*) FROM trace_events WHERE trace_id IN ({placeholders})",
        tuple(trace_ids),
    ).fetchone()
    if row is None:
        return 0
    return _required_int(row[0], field_name="deleted_event_count")


def _delete_trace_runs(connection: sqlite3.Connection, *, trace_ids: Sequence[str]) -> None:
    if not trace_ids:
        return

    placeholders = ", ".join("?" for _ in trace_ids)
    connection.execute(
        f"DELETE FROM trace_runs WHERE trace_id IN ({placeholders})",
        tuple(trace_ids),
    )


def _record_retention_failure(
    store: SqliteTraceStore,
    *,
    retention_run_id: str,
    cutoff_at: str,
    error: Exception,
) -> None:
    try:
        with open_sqlite_connection(store.database_path, settings=store.settings) as connection:
            connection.execute(
                """
                INSERT INTO trace_retention_runs (
                    retention_run_id,
                    started_at,
                    completed_at,
                    cutoff_at,
                    status,
                    error_type,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, 'failed', ?, ?)
                ON CONFLICT(retention_run_id) DO UPDATE SET
                    completed_at = excluded.completed_at,
                    status = excluded.status,
                    error_type = excluded.error_type,
                    metadata_json = excluded.metadata_json
                """,
                (
                    retention_run_id,
                    datetime.now(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                    cutoff_at,
                    type(error).__name__,
                    dumps_canonical_json({"reason": "cleanup_failed"}),
                ),
            )
            connection.commit()
    except Exception:
        return None


def _elapsed_ms(started_at: float) -> int:
    return max(int((perf_counter() - started_at) * 1000), 0)


def _trace_metric_tags(
    *,
    operation: str,
    success: bool,
    provider: str,
    error_type: str | None = None,
    event: _PreparedTraceEvent | None = None,
) -> dict[str, str]:
    tags: dict[str, str] = {
        "operation": operation,
        "provider": provider,
        "success": "true" if success else "false",
    }
    if error_type is not None:
        tags["error_type"] = error_type
    if event is not None:
        tags["event_type"] = event.event_type
        tags["event_name"] = event.event_name
    return tags