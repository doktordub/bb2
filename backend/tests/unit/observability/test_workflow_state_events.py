from __future__ import annotations

import pytest

from app.observability.events import (
    ERROR_OCCURRED,
    WORKFLOW_STATE_CONFLICT,
    WORKFLOW_STATE_LOADED,
    WORKFLOW_STATE_RESET,
    WORKFLOW_STATE_SAVED,
)
from app.observability.metrics import InMemoryMetricsRecorder
from app.observability.tracing import WorkflowStateObserver
from app.persistence.errors import WorkflowStateConflictError, WorkflowStateSerializationError
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore


def _counter_samples(snapshot: dict[str, list[object]]) -> list[object]:
    return snapshot["counters"]


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_emits_safe_success_events_and_metrics(tmp_path) -> None:
    trace_store = FakeTraceStore()
    metrics = InMemoryMetricsRecorder()
    observer = WorkflowStateObserver(store=trace_store, metrics=metrics)
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-events.db", observer=observer)
    state = {
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
            "checkpoint": {"name": "greeting"},
        },
    }

    await store.initialize()

    missing = await store.load("session-1")
    await store.save("session-1", state)
    loaded = await store.load("session-1")
    await store.reset("session-1")

    assert missing["metadata"]["loaded_empty"] is True
    assert loaded == state
    assert [event.event_type for event in trace_store.events] == [
        WORKFLOW_STATE_LOADED,
        WORKFLOW_STATE_SAVED,
        WORKFLOW_STATE_LOADED,
        WORKFLOW_STATE_RESET,
    ]

    load_miss_payload = trace_store.events[0].payload
    assert load_miss_payload["provider"] == "sqlite"
    assert load_miss_payload["operation"] == "load"
    assert load_miss_payload["found"] is False
    assert load_miss_payload["history_message_count"] == 0
    assert load_miss_payload["duration_ms"] >= 0
    assert load_miss_payload["success"] is True

    save_payload = trace_store.events[1].payload
    assert save_payload["provider"] == "sqlite"
    assert save_payload["operation"] == "save"
    assert save_payload["state_version"] == 1
    assert save_payload["state_size_bytes"] > 0
    assert save_payload["history_message_count"] == 1
    assert save_payload["duration_ms"] >= 0
    assert save_payload["success"] is True
    assert "state_json" not in save_payload

    load_hit_payload = trace_store.events[2].payload
    assert load_hit_payload["provider"] == "sqlite"
    assert load_hit_payload["operation"] == "load"
    assert load_hit_payload["found"] is True
    assert load_hit_payload["state_version"] == 1
    assert load_hit_payload["history_message_count"] == 1
    assert load_hit_payload["duration_ms"] >= 0
    assert load_hit_payload["success"] is True

    reset_payload = trace_store.events[3].payload
    assert reset_payload["provider"] == "sqlite"
    assert reset_payload["operation"] == "reset"
    assert reset_payload["reset_generation"] == 1
    assert reset_payload["cleared_state_version"] == 1
    assert reset_payload["duration_ms"] >= 0
    assert reset_payload["success"] is True

    counter_names = [sample.name for sample in _counter_samples(metrics.snapshot())]
    assert counter_names.count("backend.state.load.total") == 2
    assert "backend.state.load.miss_total" in counter_names
    assert "backend.state.save.total" in counter_names
    assert "backend.state.save.bytes" in counter_names
    assert "backend.state.reset.total" in counter_names

    load_counter = next(
        sample
        for sample in _counter_samples(metrics.snapshot())
        if sample.name == "backend.state.load.miss_total"
    )
    assert load_counter.tags == {
        "component": "persistence.workflow_state",
        "provider": "sqlite",
        "operation": "load",
        "success": "true",
    }


@pytest.mark.asyncio
async def test_sqlite_workflow_state_store_emits_failure_events_and_metrics(tmp_path) -> None:
    trace_store = FakeTraceStore()
    metrics = InMemoryMetricsRecorder()
    observer = WorkflowStateObserver(store=trace_store, metrics=metrics)
    store = SqliteWorkflowStateStore(tmp_path / "workflow-state-errors.db", observer=observer)

    await store.initialize()

    with pytest.raises(WorkflowStateSerializationError):
        await store.save("session-1", {"api_key": "top-secret"})

    assert len(trace_store.events) == 1
    event = trace_store.events[0]
    assert event.event_type == ERROR_OCCURRED
    assert event.payload == {
        "provider": "sqlite",
        "operation": "save",
        "duration_ms": event.payload["duration_ms"],
        "success": False,
        "error_type": "WorkflowStateSerializationError",
    }
    assert event.payload["duration_ms"] >= 0

    counters = _counter_samples(metrics.snapshot())
    assert any(
        sample.name == "backend.state.errors"
        and sample.tags == {
            "component": "persistence.workflow_state",
            "provider": "sqlite",
            "operation": "save",
            "success": "false",
            "error_type": "WorkflowStateSerializationError",
        }
        for sample in counters
    )
    assert any(
        sample.name == "backend.state.save.total"
        and sample.tags["success"] == "false"
        for sample in counters
    )


@pytest.mark.asyncio
async def test_workflow_state_observer_records_conflict_metrics() -> None:
    trace_store = FakeTraceStore()
    metrics = InMemoryMetricsRecorder()
    observer = WorkflowStateObserver(store=trace_store, metrics=metrics)

    await observer.record_conflict(
        operation="save",
        session_id="session-1",
        error=WorkflowStateConflictError("conflict"),
        duration_ms=7,
    )

    assert len(trace_store.events) == 1
    event = trace_store.events[0]
    assert event.event_type == WORKFLOW_STATE_CONFLICT
    assert event.payload == {
        "provider": "sqlite",
        "operation": "save",
        "duration_ms": 7,
        "success": False,
        "error_type": "WorkflowStateConflictError",
    }

    assert any(
        sample.name == "backend.state.conflicts"
        and sample.tags == {
            "component": "persistence.workflow_state",
            "provider": "sqlite",
            "operation": "save",
            "success": "false",
            "error_type": "WorkflowStateConflictError",
        }
        for sample in _counter_samples(metrics.snapshot())
    )