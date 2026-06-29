from __future__ import annotations

import sqlite3

import pytest

from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


@pytest.mark.asyncio
async def test_workflow_state_store_session_admin_list_orders_by_recent_activity(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-session-admin-ordering.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()
    await store.save("session-1", {"conversation": {"messages": [{"role": "user", "content": "one"}]}})
    await store.save(
        "session-2",
        {"conversation": {"messages": [{"role": "user", "content": "two"}]}},
        metadata={"usecase": "research"},
    )
    await store.save("session-3", {"conversation": {"messages": [{"role": "user", "content": "three"}]}})

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE workflow_sessions SET last_activity_at = ? WHERE session_id = ?",
            ("2026-06-28T09:58:00+00:00", "session-1"),
        )
        connection.execute(
            "UPDATE workflow_sessions SET last_activity_at = ? WHERE session_id = ?",
            ("2026-06-28T10:00:00+00:00", "session-2"),
        )
        connection.execute(
            "UPDATE workflow_sessions SET last_activity_at = ? WHERE session_id = ?",
            ("2026-06-28T09:59:00+00:00", "session-3"),
        )
        connection.commit()

    listed = await store.list_sessions(limit=2)

    assert listed.limit == 2
    assert listed.has_more is True
    assert [session.session_id for session in listed.sessions] == ["session-2", "session-3"]
    assert listed.sessions[0].usecase == "research"


@pytest.mark.asyncio
async def test_workflow_state_store_session_admin_delete_is_isolated_from_other_sessions(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-session-admin-delete.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()
    await store.save(
        "session-1",
        {"conversation": {"messages": [{"role": "user", "content": "delete me"}]}},
    )
    await store.reset("session-1", reason="cleanup")
    await store.save(
        "session-2",
        {"conversation": {"messages": [{"role": "user", "content": "keep me"}]}},
    )

    deleted = await store.delete_session("session-1")
    loaded_other = await store.load("session-2")
    listed = await store.list_sessions(limit=10)

    assert deleted.deleted is True
    assert loaded_other.version == 1
    assert [session.session_id for session in listed.sessions] == ["session-2"]

    with sqlite3.connect(database_path) as connection:
        deleted_rows = connection.execute(
            "SELECT COUNT(*) FROM workflow_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        other_rows = connection.execute(
            "SELECT COUNT(*) FROM workflow_sessions WHERE session_id = ?",
            ("session-2",),
        ).fetchone()

    assert deleted_rows == (0,)
    assert other_rows == (1,)