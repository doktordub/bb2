"""SQLite-backed trace store implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.contracts.trace import TraceEvent, TraceReadModel, TraceSearchFilters, TraceSummary
from app.persistence.errors import PersistenceConfigurationError, PersistenceSerializationError, TraceStoreError
from app.persistence.serialization import dumps_json
from app.persistence.settings import SqliteStoreSettings
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite_trace_schema import ensure_trace_schema


class SqliteTraceStore:
    """Append-only SQLite trace-event persistence."""

    def __init__(
        self,
        database_path: Path,
        *,
        settings: SqliteStoreSettings | None = None,
    ) -> None:
        self._database_path = database_path
        self._settings = settings or SqliteStoreSettings(
            path=database_path,
            create_parent_dirs=True,
            initialize_schema=True,
            journal_mode="WAL",
            synchronous="NORMAL",
            busy_timeout_ms=5000,
            foreign_keys=True,
            required=True,
        )

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def settings(self) -> SqliteStoreSettings:
        return self._settings

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def record_event(self, event: TraceEvent) -> None:
        await asyncio.to_thread(self._record_event_sync, event)

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        for event in events:
            await self.record_event(event)

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> TraceReadModel:
        raise TraceStoreError(
            "Trace read is not implemented for the current SQLite trace schema."
        )

    async def search_traces(self, *, filters: TraceSearchFilters) -> list[TraceSummary]:
        raise TraceStoreError(
            "Trace search is not implemented for the current SQLite trace schema."
        )

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._health_sync)

    def _initialize_sync(self) -> None:
        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
                if self._settings.initialize_schema:
                    ensure_trace_schema(connection)
                connection.commit()
        except PersistenceConfigurationError:
            raise
        except Exception as exc:
            raise TraceStoreError("Trace store initialization failed.") from exc

    def _record_event_sync(self, event: TraceEvent) -> None:
        try:
            payload_json = dumps_json(event.payload)
        except PersistenceSerializationError as exc:
            raise TraceStoreError("Trace store payload serialization failed.") from exc

        try:
            with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
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
                        event.trace_id,
                        event.session_id,
                        event.user_id,
                        event.usecase,
                        event.event_type,
                        event.component,
                        event.timestamp.isoformat(),
                        payload_json,
                    ),
                )
                connection.commit()
        except Exception as exc:
            raise TraceStoreError("Trace store write failed.") from exc

    def _health_sync(self) -> dict[str, Any]:
        with open_sqlite_connection(self._database_path, settings=self._settings) as connection:
            connection.execute("SELECT 1")

        return {
            "status": "ok",
            "configured": True,
            "provider": "sqlite",
            "database_exists": self._database_path.exists(),
        }