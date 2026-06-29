from __future__ import annotations

import sqlite3
from typing import Any, cast

import pytest

from app.contracts.state import WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE
from app.persistence.errors import (
    WorkflowStateConflictError,
    WorkflowStateError,
    WorkflowStateSerializationError,
    WorkflowStateSizeError,
)
from app.persistence.settings import SqliteWorkflowStateSettings
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_load_returns_default_state_for_missing_session(
    tmp_path,
) -> None:
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-missing.db")

    await store.initialize()
    loaded = await store.load("session-1")

    assert loaded.session_id == "session-1"
    assert loaded.version is None
    assert loaded.found is False
    assert loaded.loaded_empty is True
    assert loaded.state["conversation"] == {"messages": []}
    assert loaded.state["workflow"] == {
        "current_step": None,
        "checkpoint": None,
        "scratch": {},
        "pending_actions": [],
    }
    assert loaded.state["metadata"]["loaded_empty"] is True
    assert loaded.state["metadata"]["created_at"]


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_normalizes_session_id_on_save_and_load(tmp_path) -> None:
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-normalized.db")
    state = {"workflow": {"current_step": "draft"}}

    await store.initialize()
    save_result = await store.save("  session-1  ", state)

    loaded = await store.load("session-1")
    assert save_result.version == 1
    assert loaded.state == state
    assert loaded.version == 1
    assert loaded.found is True


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_rejects_invalid_session_ids(tmp_path) -> None:
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-invalid-session.db")

    await store.initialize()

    with pytest.raises(WorkflowStateError, match="Invalid workflow-state session identifier"):
        await store.save("  ", {"workflow": {}})


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_rejects_non_mapping_payload(tmp_path) -> None:
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-invalid-payload.db")

    await store.initialize()

    with pytest.raises(WorkflowStateSerializationError, match="JSON object"):
        await store.save("session-1", cast(dict[str, Any], ["not", "a", "mapping"]))


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_rejects_oversized_payload(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-too-large.db"
    store = SqliteWorkflowStateStore(
        database_path,
        settings=_build_settings(database_path, max_state_bytes=96),
    )

    await store.initialize()

    with pytest.raises(WorkflowStateSizeError, match="configured size limit") as exc_info:
        await store.save("session-1", {"conversation": {"messages": [{"content": "x" * 256}]}})

    assert exc_info.value.details == {
        "operation": "save",
        "state_size_bytes": exc_info.value.details["state_size_bytes"],
        "max_state_bytes": 96,
    }
    assert exc_info.value.details["state_size_bytes"] > 96


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_rejects_sensitive_fields(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-sensitive.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()

    with pytest.raises(WorkflowStateSerializationError, match="sensitive field names") as exc_info:
        await store.save(
            "session-1",
            {
                "workflow": {
                    "scratch": {
                        "api_key": "secret-value",
                    }
                }
            },
        )

    assert exc_info.value.details["operation"] == "save"
    assert exc_info.value.details["field_name"] == "api_key"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT session_id FROM workflow_state_current WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

    assert row is None


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_raises_for_corrupt_stored_json(tmp_path) -> None:
    database_path = tmp_path / "workflow-state-corrupt.db"
    store = SqliteWorkflowStateStore(database_path)

    await store.initialize()
    await store.save("session-1", {"workflow": {"current_step": "draft"}})

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE workflow_state_current SET state_json = ? WHERE session_id = ?",
            ("{", "session-1"),
        )
        connection.commit()

    with pytest.raises(WorkflowStateSerializationError, match="invalid JSON"):
        await store.load("session-1")


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_save_uses_expected_version(tmp_path) -> None:
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-versioned.db")

    await store.initialize()

    first = await store.save("session-1", {"count": 1})
    second = await store.save("session-1", {"count": 2}, expected_version=first.version)

    assert first.version == 1
    assert second.version == 2

    with pytest.raises(WorkflowStateConflictError, match="current version"):
        await store.save("session-1", {"count": 3}, expected_version=1)


def _build_settings(
    database_path,
    *,
    max_state_bytes: int,
) -> SqliteWorkflowStateSettings:
    return SqliteWorkflowStateSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
        max_state_bytes=max_state_bytes,
        max_history_messages=50,
        reset_mode=WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
        store_user_id=False,
        store_user_id_hash=True,
    )