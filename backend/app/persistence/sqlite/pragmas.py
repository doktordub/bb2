"""SQLite pragma helpers shared by persistence adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.persistence.errors import PersistenceConfigurationError

_ALLOWED_JOURNAL_MODES = frozenset({"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"})
_ALLOWED_SYNCHRONOUS_MODES = frozenset({"NORMAL", "FULL"})


class SupportsExecute(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
        ...


@dataclass(frozen=True, slots=True)
class SqlitePragmas:
    """Resolved pragma values applied to SQLite connections."""

    journal_mode: str
    synchronous: str
    busy_timeout_ms: int
    foreign_keys: bool


def apply_sqlite_pragmas(connection: SupportsExecute, pragmas: SqlitePragmas) -> None:
    """Apply a safe subset of configured SQLite pragmas."""

    journal_mode = pragmas.journal_mode.strip().upper()
    if journal_mode not in _ALLOWED_JOURNAL_MODES:
        raise PersistenceConfigurationError(
            f"Unsupported SQLite journal_mode: {pragmas.journal_mode}"
        )

    synchronous = pragmas.synchronous.strip().upper()
    if synchronous not in _ALLOWED_SYNCHRONOUS_MODES:
        raise PersistenceConfigurationError(
            f"Unsupported SQLite synchronous mode: {pragmas.synchronous}"
        )

    if pragmas.busy_timeout_ms < 0:
        raise PersistenceConfigurationError("SQLite busy_timeout_ms must be non-negative.")

    connection.execute(f"PRAGMA journal_mode = {journal_mode}")
    connection.execute(f"PRAGMA synchronous = {synchronous}")
    connection.execute(f"PRAGMA busy_timeout = {int(pragmas.busy_timeout_ms)}")
    connection.execute(f"PRAGMA foreign_keys = {'ON' if pragmas.foreign_keys else 'OFF'}")