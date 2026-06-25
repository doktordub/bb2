"""Idempotent SQLite schema-version helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol


SCHEMA_VERSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    name TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
"""


class SupportsFetchResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None:
        ...

    def fetchall(self) -> list[tuple[object, ...]]:
        ...


class SupportsMigration(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> SupportsFetchResult:
        ...

    def executescript(self, sql_script: str) -> object:
        ...


def ensure_schema_version_table(connection: SupportsMigration) -> None:
    """Create the shared schema-version table when it is missing."""

    connection.executescript(SCHEMA_VERSION_TABLE_SQL)


def get_schema_version(connection: SupportsMigration, *, name: str) -> int | None:
    """Return the applied schema version for a named SQLite schema."""

    row = connection.execute(
        "SELECT version FROM schema_version WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return None

    value = row[0]
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)

    raise TypeError(
        f"Invalid schema version value for {name!r}: {type(value).__name__}"
    )


def table_exists(connection: SupportsMigration, *, name: str) -> bool:
    """Return whether a named table exists in the current SQLite database."""

    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def ensure_schema(
    connection: SupportsMigration,
    *,
    name: str,
    target_version: int,
    apply_schema: Callable[[SupportsMigration], None],
) -> None:
    """Apply an idempotent schema bootstrap and record its version."""

    ensure_schema_version_table(connection)
    current_version = get_schema_version(connection, name=name)
    if current_version is not None and current_version >= target_version:
        return

    apply_schema(connection)
    connection.execute(
        """
        INSERT INTO schema_version (name, version, applied_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            version = excluded.version,
            applied_at = excluded.applied_at
        """,
        (name, target_version, datetime.now(UTC).isoformat()),
    )