from __future__ import annotations

import pytest

from app.contracts.errors import WorkflowStateError
from app.testing.fakes.fake_state import FakeWorkflowStateStore


async def test_fake_workflow_state_store_load_returns_copy_and_missing_state_is_default() -> None:
    store = FakeWorkflowStateStore()

    missing = await store.load("missing-session")
    assert missing["session_id"] == "missing-session"
    assert missing["conversation"] == {"messages": []}
    assert missing["workflow"] == {
        "current_step": None,
        "checkpoint": None,
        "scratch": {},
        "pending_actions": [],
    }
    assert missing["metadata"]["loaded_empty"] is True

    await store.save("session-1", {"workflow": {"scratch": {"step": "draft"}}})
    loaded = await store.load("session-1")
    loaded["workflow"]["scratch"]["step"] = "mutated"

    assert store.states["session-1"] == {"workflow": {"scratch": {"step": "draft"}}}
    assert store.load_requests == ["missing-session", "session-1"]


async def test_fake_workflow_state_store_save_reset_and_health() -> None:
    store = FakeWorkflowStateStore()

    await store.save("session-1", {"count": 1})
    await store.reset("session-1")

    assert store.save_requests == [("session-1", {"count": 1})]
    assert store.reset_requests == ["session-1"]
    reset_state = await store.load("session-1")
    assert reset_state["session_id"] == "session-1"
    assert reset_state["metadata"]["loaded_empty"] is True
    assert await store.health() == {
        "status": "ok",
        "configured": True,
        "provider": "fake",
    }


async def test_fake_workflow_state_store_rejects_invalid_session_ids() -> None:
    store = FakeWorkflowStateStore()

    with pytest.raises(WorkflowStateError, match="Invalid workflow-state session identifier"):
        await store.load("  ")