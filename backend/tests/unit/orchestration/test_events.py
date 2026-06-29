from __future__ import annotations

from app.orchestration.errors import AgentExecutionError, OrchestrationErrorDetail
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.result_builder import build_orchestration_result


def test_event_factories_cover_minimal_v1_event_set() -> None:
    result = build_orchestration_result(
        answer="hello",
        session_id="session_123",
        trace_id="trace_123",
        usecase="default_chat",
        strategy_name="direct_agent",
        agent_name="support_agent",
    )

    events = [
        OrchestrationStreamEvent.started(
            trace_id="trace_123",
            session_id="session_123",
        ),
        OrchestrationStreamEvent.strategy_selected(
            trace_id="trace_123",
            session_id="session_123",
            strategy_name="direct_agent",
            usecase="default_chat",
            agent_name="support_agent",
        ),
        OrchestrationStreamEvent.response_delta(
            trace_id="trace_123",
            session_id="session_123",
            text="hel",
        ),
        OrchestrationStreamEvent.response_completed(
            trace_id="trace_123",
            session_id="session_123",
            finish_reason="stop",
        ),
        OrchestrationStreamEvent.completed(
            trace_id="trace_123",
            session_id="session_123",
            result=result,
        ),
        OrchestrationStreamEvent.error_event(
            trace_id="trace_123",
            session_id="session_123",
            error=AgentExecutionError(),
        ),
        OrchestrationStreamEvent.cancelled(
            trace_id="trace_123",
            session_id="session_123",
        ),
    ]

    assert [event.type for event in events] == [
        "orchestration.started",
        "strategy.selected",
        "response.delta",
        "response.completed",
        "orchestration.completed",
        "orchestration.error",
        "orchestration.cancelled",
    ]
    assert events[2].text == "hel"
    assert events[4].result == result


def test_error_event_and_metadata_are_sanitized() -> None:
    event = OrchestrationStreamEvent.error_event(
        trace_id="trace_123",
        session_id="session_123",
        error=OrchestrationErrorDetail(
            code="agent_execution_failed",
            message="The agent could not complete the request.",
            retryable=True,
            metadata={"stack_trace": "hidden", "attempt": 2},
        ),
        metadata={"provider_payload": {"raw": True}, "safe": "ok"},
    )

    assert event.error is not None
    assert event.error.metadata == {"attempt": 2}
    assert event.metadata == {"safe": "ok"}