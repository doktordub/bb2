"""SQLite connection lifecycle helpers for backend persistence adapters."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from app.persistence.errors import PersistenceUnavailableError
from app.persistence.settings import SqliteStoreSettings
from app.persistence.sqlite.pragmas import SqlitePragmas, apply_sqlite_pragmas


@contextmanager
def open_sqlite_connection(
    database_path: Path,
    *,
    settings: SqliteStoreSettings,
) -> Iterator[sqlite3.Connection]:
    """Open a configured SQLite connection with shared pragma application."""

    if settings.create_parent_dirs:
        database_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        raise PersistenceUnavailableError(
            f"Unable to open SQLite database '{database_path.name}'."
        ) from exc

    try:
        apply_sqlite_pragmas(
            connection,
            SqlitePragmas(
                journal_mode=settings.journal_mode,
                synchronous=settings.synchronous,
                busy_timeout_ms=settings.busy_timeout_ms,
                foreign_keys=settings.foreign_keys,
            ),
        )
        yield connection
    except sqlite3.Error as exc:
        raise PersistenceUnavailableError(
            f"SQLite operation failed for '{database_path.name}'."
        ) from exc
    finally:
        connection.close()