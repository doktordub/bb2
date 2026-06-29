from __future__ import annotations

import asyncio
import json

import pytest

from app.persistence.errors import WorkflowStateConflictError
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


def _build_state(index: int) -> dict[str, object]:
    return {
        "conversation": {
            "messages": [
                {
                    "role": "user",
                    "content": f"message-{index}",
                }
            ]
        },
        "workflow": {
            "current_step": f"step-{index}",
            "checkpoint": {"name": f"checkpoint-{index}"},
        },
    }


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_concurrent_saves_do_not_corrupt_current_row(
    tmp_path,
) -> None:
    database_path = tmp_path / "workflow-state-concurrency.db"
    store = SqliteWorkflowStateStore(database_path)
    states = [_build_state(index) for index in range(10)]

    await store.initialize()
    await asyncio.gather(*(store.save("session-1", state) for state in states))

    loaded = await store.load("session-1")
    assert loaded.state in states
    assert loaded.version == len(states)

    with open_sqlite_connection(database_path, settings=store.settings) as connection:
        current_row = connection.execute(
            """
            SELECT state_json, state_version, message_count, current_step, checkpoint_name, reset_generation
            FROM workflow_state_current
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()

    assert current_row is not None
    assert json.loads(current_row[0]) in states
    assert current_row[1] == len(states)
    assert current_row[2] == 1
    assert current_row[3].startswith("step-")
    assert current_row[4].startswith("checkpoint-")
    assert current_row[5] == 0

    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert synchronous == (1,)
    assert busy_timeout == (5000,)
    assert foreign_keys == (1,)


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_rejects_stale_expected_version_under_concurrency(
    tmp_path,
) -> None:
    database_path = tmp_path / "workflow-state-concurrency-version.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()

    first = await store.save("session-1", _build_state(0))
    second = await store.save("session-1", _build_state(1), expected_version=first.version)

    assert second.version == 2

    with pytest.raises(WorkflowStateConflictError, match="current version"):
        await store.save("session-1", _build_state(2), expected_version=first.version)