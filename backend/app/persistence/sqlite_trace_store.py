"""SQLite-backed trace store implementation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.contracts.trace import TraceEvent
from app.persistence.sqlite_trace_schema import ensure_trace_schema


class SqliteTraceStore:
    """Append-only SQLite trace-event persistence."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    @property
    def database_path(self) -> Path:
        return self._database_path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def record_event(self, event: TraceEvent) -> None:
        await asyncio.to_thread(self._record_event_sync, event)

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._health_sync)

    def _initialize_sync(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._database_path) as connection:
            ensure_trace_schema(connection)
            connection.commit()

    def _record_event_sync(self, event: TraceEvent) -> None:
        with sqlite3.connect(self._database_path) as connection:
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
                    json.dumps(event.payload, separators=(",", ":"), ensure_ascii=True),
                ),
            )
            connection.commit()

    def _health_sync(self) -> dict[str, Any]:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute("SELECT 1")

        return {
            "status": "ok",
            "configured": True,
            "provider": "sqlite",
            "database_exists": self._database_path.exists(),
        }