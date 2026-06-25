from __future__ import annotations

import json
import sqlite3

import pytest

from app.contracts.state import (
    WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW,
)
from app.persistence.settings import SqliteWorkflowStateSettings
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_reset_replaces_with_default_state(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-reset-replace.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()
    await store.save(
        "session-1",
        {
            "conversation": {"messages": [{"role": "user", "content": "hello"}]},
            "workflow": {"current_step": "draft", "checkpoint": {"name": "before_reset"}},
        },
    )
    await store.reset("session-1")

    loaded = await store.load("session-1")
    assert loaded["session_id"] == "session-1"
    assert loaded["conversation"] == {"messages": []}
    assert loaded["workflow"]["current_step"] is None
    assert loaded["workflow"]["checkpoint"] is None
    assert loaded["metadata"]["loaded_empty"] is True

    with sqlite3.connect(database_path) as connection:
        reset_row = connection.execute(
            "SELECT reset_generation, cleared_state_version FROM workflow_state_resets WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        current_row = connection.execute(
            "SELECT state_json, message_count, current_step, checkpoint_name, state_version, reset_generation FROM workflow_state_current WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

    assert reset_row == (1, 1)
    assert current_row is not None
    assert json.loads(current_row[0]) == loaded
    assert current_row[1] == 0
    assert current_row[2] is None
    assert current_row[3] is None
    assert current_row[4] == 2
    assert current_row[5] == 1


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_delete_reset_mode_removes_current_row(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-reset-delete.db"
    store = SqliteWorkflowStateStore(
        database_path,
        settings=_build_settings(database_path, reset_mode=WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW),
    )

    await store.initialize()
    await store.save("session-1", {"workflow": {"current_step": "draft"}})
    await store.reset("session-1")

    loaded = await store.load("session-1")
    assert loaded["session_id"] == "session-1"
    assert loaded["metadata"]["loaded_empty"] is True

    with sqlite3.connect(database_path) as connection:
        current_row = connection.execute(
            "SELECT session_id FROM workflow_state_current WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        reset_row = connection.execute(
            "SELECT reset_generation, cleared_state_version FROM workflow_state_resets WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

    assert current_row is None
    assert reset_row == (1, 1)


def _build_settings(database_path, *, reset_mode: str) -> SqliteWorkflowStateSettings:
    return SqliteWorkflowStateSettings(
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
        reset_mode=reset_mode,
        store_user_id=False,
        store_user_id_hash=True,
    )