from __future__ import annotations

import pytest

from app.contracts.errors import WorkflowStateError
from app.persistence.errors import WorkflowStateConflictError
from app.testing.fakes.fake_state import FakeWorkflowStateStore


async def test_fake_workflow_state_store_load_returns_copy_and_missing_state_is_default() -> None:
    store = FakeWorkflowStateStore()

    missing = await store.load("missing-session")
    assert missing.session_id == "missing-session"
    assert missing.version is None
    assert missing.found is False
    assert missing.loaded_empty is True
    assert missing.state["conversation"] == {"messages": []}
    assert missing.state["workflow"] == {
        "current_step": None,
        "checkpoint": None,
        "scratch": {},
        "pending_actions": [],
    }
    assert missing.state["metadata"]["loaded_empty"] is True

    save_result = await store.save("session-1", {"workflow": {"scratch": {"step": "draft"}}})
    loaded = await store.load("session-1")
    loaded.state["workflow"]["scratch"]["step"] = "mutated"

    assert store.states["session-1"] == {"workflow": {"scratch": {"step": "draft"}}}
    assert save_result.version == 1
    assert store.load_requests == ["missing-session", "session-1"]


async def test_fake_workflow_state_store_save_reset_and_health() -> None:
    store = FakeWorkflowStateStore()

    save_result = await store.save("session-1", {"count": 1})
    reset_result = await store.reset("session-1", reason="user_requested")

    assert store.save_requests == [("session-1", {"count": 1})]
    assert store.reset_requests == ["session-1"]
    assert save_result.version == 1
    assert reset_result.reset_generation == 1
    assert reset_result.cleared_version == 1
    assert reset_result.deleted is True
    reset_state = await store.load("session-1")
    assert reset_state.session_id == "session-1"
    assert reset_state.loaded_empty is True
    assert reset_state.state["metadata"]["loaded_empty"] is True
    assert await store.health() == {
        "status": "ok",
        "configured": True,
        "provider": "fake",
    }


async def test_fake_workflow_state_store_enforces_expected_version_and_supports_conflicts() -> None:
    store = FakeWorkflowStateStore()

    first = await store.save("session-1", {"count": 1})
    second = await store.save("session-1", {"count": 2}, expected_version=first.version)

    assert first.version == 1
    assert second.version == 2
    assert store.save_calls[1].expected_version == 1

    with pytest.raises(WorkflowStateConflictError, match="current version"):
        await store.save("session-1", {"count": 3}, expected_version=1)

    store.queue_conflict("session-1")
    with pytest.raises(WorkflowStateConflictError, match="current version"):
        await store.save("session-1", {"count": 4}, expected_version=2)


async def test_fake_workflow_state_store_rejects_invalid_session_ids() -> None:
    store = FakeWorkflowStateStore()

    with pytest.raises(WorkflowStateError, match="Invalid workflow-state session identifier"):
        await store.load("  ")