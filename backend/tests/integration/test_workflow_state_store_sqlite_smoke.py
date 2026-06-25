from __future__ import annotations

import json
import sqlite3

import pytest

from app.persistence.serialization import dumps_canonical_json
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_save_load_reset_and_health(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-smoke.db"
    store = SqliteWorkflowStateStore(database_path)
    state_v1 = {
        "conversation": {
            "messages": [
                {
                    "role": "user",
                    "content": "hello",
                }
            ]
        },
        "workflow": {
            "current_step": "intake",
            "checkpoint": {
                "name": "greeting",
            },
        },
    }
    state_v2 = {
        "conversation": {
            "messages": [
                {
                    "role": "assistant",
                    "content": "hi",
                }
            ]
        },
        "workflow": {
            "current_step": "responded",
            "checkpoint": {
                "name": "reply",
            },
        },
    }

    await store.initialize()
    missing = await store.load("session-1")
    assert missing["session_id"] == "session-1"
    assert missing["conversation"] == {"messages": []}
    assert missing["metadata"]["loaded_empty"] is True

    await store.save("session-1", state_v1)
    await store.save("session-1", state_v2)

    loaded = await store.load("session-1")
    assert loaded == state_v2

    health = await store.health()
    assert health == {
        "status": "ok",
        "configured": True,
        "provider": "sqlite",
        "required": True,
        "database_exists": True,
        "schema_initialized": True,
        "schema_version": 2,
        "journal_mode": "wal",
        "synchronous": "normal",
    }

    with sqlite3.connect(database_path) as connection:
        session_row = connection.execute(
            """
            SELECT status, reset_count, created_at, updated_at, last_activity_at, metadata_json
            FROM workflow_sessions
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()
        state_row = connection.execute(
            """
            SELECT
                state_json,
                state_hash,
                state_size_bytes,
                message_count,
                current_step,
                checkpoint_name,
                state_version,
                created_at,
                updated_at,
                reset_generation
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()

    assert session_row is not None
    assert session_row[0] == "active"
    assert session_row[1] == 0
    assert session_row[2]
    assert session_row[3]
    assert session_row[4]
    assert json.loads(session_row[5]) == {}

    assert state_row is not None
    assert json.loads(state_row[0]) == state_v2
    assert state_row[1]
    assert state_row[2] == len(dumps_canonical_json(state_v2).encode("utf-8"))
    assert state_row[3] == 1
    assert state_row[4] == "responded"
    assert state_row[5] == "reply"
    assert state_row[6] == 2
    assert state_row[7]
    assert state_row[8]
    assert state_row[9] == 0

    await store.reset("session-1")
    reset_state = await store.load("session-1")
    assert reset_state["session_id"] == "session-1"
    assert reset_state["conversation"] == {"messages": []}
    assert reset_state["workflow"]["current_step"] is None
    assert reset_state["workflow"]["checkpoint"] is None
    assert reset_state["metadata"]["loaded_empty"] is True

    with sqlite3.connect(database_path) as connection:
        reset_row = connection.execute(
            """
            SELECT reset_generation, cleared_state_version, reset_at
            FROM workflow_state_resets
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()
        session_after_reset = connection.execute(
            "SELECT reset_count FROM workflow_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        current_after_reset = connection.execute(
            """
            SELECT state_json, message_count, current_step, checkpoint_name, state_version, reset_generation
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()

    assert reset_row is not None
    assert reset_row[0] == 1
    assert reset_row[1] == 2
    assert reset_row[2]
    assert session_after_reset == (1,)
    assert current_after_reset is not None
    assert json.loads(current_after_reset[0]) == reset_state
    assert current_after_reset[1:] == (0, None, None, 3, 1)


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_reopens_existing_database(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-reopen.db"
    first_store = SqliteWorkflowStateStore(database_path)
    second_store = SqliteWorkflowStateStore(database_path)
    state = {
        "conversation": {
            "messages": [
                {
                    "role": "user",
                    "content": "persist me",
                }
            ]
        }
    }

    await first_store.initialize()
    await first_store.save("session-1", state)

    await second_store.initialize()
    assert await second_store.load("session-1") == state


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_migrates_legacy_workflow_states_table(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-legacy.db"
    legacy_state = {
        "conversation": {
            "messages": [
                {
                    "role": "assistant",
                    "content": "from legacy",
                }
            ]
        },
        "workflow": {
            "current_step": "legacy_step",
            "checkpoint": {
                "name": "legacy_checkpoint",
            },
        },
    }

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_states (
                session_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_states_updated_at
                ON workflow_states(updated_at);
            """
        )
        connection.execute(
            """
            INSERT INTO schema_version (name, version, applied_at)
            VALUES ('workflow_state_store', 1, '2026-06-24T12:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO workflow_states (
                session_id,
                state_json,
                metadata_json,
                version,
                created_at,
                updated_at
            )
            VALUES (?, ?, '{}', 4, '2026-06-24T12:00:00+00:00', '2026-06-24T12:05:00+00:00')
            """,
            ("session-1", json.dumps(legacy_state)),
        )
        connection.commit()

    store = SqliteWorkflowStateStore(database_path)
    await store.initialize()

    assert await store.load("session-1") == legacy_state

    with sqlite3.connect(database_path) as connection:
        schema_version = connection.execute(
            "SELECT version FROM schema_version WHERE name = 'workflow_state_store'"
        ).fetchone()
        backup_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_states_legacy_v1'"
        ).fetchone()
        migrated_session = connection.execute(
            "SELECT reset_count FROM workflow_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        migrated_state = connection.execute(
            """
            SELECT state_version, message_count, current_step, checkpoint_name, reset_generation
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()

    assert schema_version == (2,)
    assert backup_table == ("workflow_states_legacy_v1",)
    assert migrated_session == (0,)
    assert migrated_state == (4, 1, "legacy_step", "legacy_checkpoint", 0)