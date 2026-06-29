from __future__ import annotations

import sqlite3

import pytest

from app.persistence.errors import WorkflowStateError
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_list_sessions_returns_safe_recent_summaries(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-session-admin.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()
    await store.save(
        "session-1",
        {
            "conversation": {
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ]
            }
        },
        metadata={
            "usecase": "default_chat",
            "user_id": "user-1",
            "user_id_hash": "sha256:user-1",
        },
    )
    await store.save(
        "session-2",
        {"conversation": {"messages": [{"role": "user", "content": "other"}]}},
        metadata={
            "usecase": "research",
            "user_id": "user-2",
            "user_id_hash": "sha256:user-2",
        },
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE workflow_sessions SET updated_at = ?, last_activity_at = ? WHERE session_id = ?",
            ("2026-06-28T09:59:00+00:00", "2026-06-28T09:59:00+00:00", "session-2"),
        )
        connection.execute(
            "UPDATE workflow_sessions SET updated_at = ?, last_activity_at = ? WHERE session_id = ?",
            ("2026-06-28T10:00:00+00:00", "2026-06-28T10:00:00+00:00", "session-1"),
        )
        connection.commit()

    listed = await store.list_sessions(limit=1)

    assert listed.limit == 1
    assert listed.has_more is True
    assert [session.session_id for session in listed.sessions] == ["session-1"]

    summary = listed.sessions[0]
    assert summary.usecase == "default_chat"
    assert summary.status == "active"
    assert summary.reset_count == 0
    assert summary.message_count == 2
    assert summary.created_at is not None
    assert summary.updated_at is not None
    assert summary.last_activity_at is not None

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT user_id, user_id_hash, usecase FROM workflow_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

    assert row == (None, "sha256:user-1", "default_chat")


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_list_sessions_rejects_non_positive_limits(tmp_path) -> None:
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-invalid-limit.db")

    with pytest.raises(WorkflowStateError, match="session list limit"):
        await store.list_sessions(limit=0)


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_delete_session_removes_cascaded_rows(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-session-delete.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()
    await store.save(
        "session-1",
        {"conversation": {"messages": [{"role": "user", "content": "hello"}]}},
        metadata={"usecase": "default_chat"},
    )
    await store.reset("session-1", reason="cleanup")
    await store.save(
        "session-2",
        {"conversation": {"messages": [{"role": "user", "content": "keep"}]}},
        metadata={"usecase": "support"},
    )

    deleted = await store.delete_session("session-1")
    missing = await store.delete_session("missing-session")

    assert deleted.session_id == "session-1"
    assert deleted.deleted is True
    assert missing.session_id == "missing-session"
    assert missing.deleted is False

    with sqlite3.connect(database_path) as connection:
        session_row = connection.execute(
            "SELECT session_id FROM workflow_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        current_row = connection.execute(
            "SELECT session_id FROM workflow_state_current WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        reset_row = connection.execute(
            "SELECT session_id FROM workflow_state_resets WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        other_session_row = connection.execute(
            "SELECT session_id FROM workflow_sessions WHERE session_id = ?",
            ("session-2",),
        ).fetchone()

    assert session_row is None
    assert current_row is None
    assert reset_row is None
    assert other_session_row == ("session-2",)