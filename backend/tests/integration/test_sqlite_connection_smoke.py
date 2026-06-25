from __future__ import annotations

from pathlib import Path

from app.persistence.settings import SqliteStoreSettings
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite.migrations import ensure_schema, get_schema_version


def test_open_sqlite_connection_applies_pragmas_and_bootstraps_schema_version(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sqlite-connection-smoke.db"
    settings = SqliteStoreSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="FULL",
        busy_timeout_ms=4321,
        foreign_keys=True,
        required=True,
    )

    with open_sqlite_connection(database_path, settings=settings) as connection:
        ensure_schema(
            connection,
            name="smoke",
            target_version=1,
            apply_schema=lambda active_connection: active_connection.execute(
                "CREATE TABLE IF NOT EXISTS smoke_items (id INTEGER PRIMARY KEY)"
            ),
        )
        connection.commit()

        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        schema_version = connection.execute(
            "SELECT version FROM schema_version WHERE name = ?",
            ("smoke",),
        ).fetchone()
        smoke_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'smoke_items'"
        ).fetchone()

    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert synchronous == (2,)
    assert busy_timeout == (4321,)
    assert foreign_keys == (1,)
    assert schema_version == (1,)
    assert smoke_table == ("smoke_items",)
    assert get_schema_version_for_file(database_path) == 1


def get_schema_version_for_file(database_path: Path) -> int | None:
    settings = SqliteStoreSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
    )

    with open_sqlite_connection(database_path, settings=settings) as connection:
        return get_schema_version(connection, name="smoke")