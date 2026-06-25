from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from app.contracts.health import HEALTH_FAILED, HEALTH_OK
from app.contracts.state import WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE
from app.persistence.settings import SqliteWorkflowStateSettings
from app.persistence.sqlite_workflow_state_schema import (
    WORKFLOW_STATE_SCHEMA_NAME,
    WORKFLOW_STATE_SCHEMA_VERSION,
)
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_health_reports_ok_without_exposing_paths(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workflow-state-health.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()

    health = await store.health()

    assert health == {
        "status": HEALTH_OK,
        "configured": True,
        "provider": "sqlite",
        "required": True,
        "database_exists": True,
        "journal_mode": "wal",
        "synchronous": "normal",
        "schema_initialized": True,
        "schema_version": WORKFLOW_STATE_SCHEMA_VERSION,
    }

    health_json = json.dumps(health)
    assert str(tmp_path) not in health_json
    assert database_path.as_posix() not in health_json


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_health_reports_missing_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workflow-state-no-schema.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        connection.commit()
    store = SqliteWorkflowStateStore(
        database_path,
        settings=_build_settings(database_path, initialize_schema=False),
    )

    health = await store.health()

    assert health == {
        "status": HEALTH_FAILED,
        "configured": True,
        "provider": "sqlite",
        "required": True,
        "database_exists": True,
        "journal_mode": "wal",
        "synchronous": "normal",
        "schema_initialized": False,
        "schema_version": None,
        "reason": "schema_not_initialized",
    }


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_health_reports_schema_mismatch(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workflow-state-mismatch.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO schema_version (name, version, applied_at)
            VALUES (?, 999, '2026-06-24T12:00:00+00:00')
            """,
            (WORKFLOW_STATE_SCHEMA_NAME,),
        )
        connection.commit()

    store = SqliteWorkflowStateStore(database_path)

    health = await store.health()

    assert health == {
        "status": HEALTH_FAILED,
        "configured": True,
        "provider": "sqlite",
        "required": True,
        "database_exists": True,
        "journal_mode": "wal",
        "synchronous": "normal",
        "schema_initialized": True,
        "schema_version": 999,
        "reason": "schema_version_mismatch",
        "expected_schema_version": WORKFLOW_STATE_SCHEMA_VERSION,
    }


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_health_reports_unavailable_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workflow-state-unavailable.db"
    database_path.mkdir()
    store = SqliteWorkflowStateStore(database_path)

    health = await store.health()

    assert health == {
        "status": HEALTH_FAILED,
        "configured": True,
        "provider": "sqlite",
        "required": True,
        "database_exists": True,
        "journal_mode": "wal",
        "synchronous": "normal",
        "reason": "database_unavailable",
        "error_type": "PersistenceUnavailableError",
    }

    health_json = json.dumps(health)
    assert str(tmp_path) not in health_json
    assert database_path.as_posix() not in health_json


def _build_settings(
    database_path: Path,
    *,
    initialize_schema: bool,
) -> SqliteWorkflowStateSettings:
    return SqliteWorkflowStateSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=initialize_schema,
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