from __future__ import annotations

from app.contracts.results import StreamEvent
from app.orchestration.errors import AgentExecutionError
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.stream_mapping import map_stream_event


def test_map_stream_event_translates_legacy_content_delta() -> None:
    mapped = map_stream_event(
        StreamEvent(event_type="content_delta", data={"text": "hello"}),
        trace_id="trace_1",
        session_id="session_1",
    )

    assert mapped.answer_delta == "hello"
    assert mapped.emitted_events[0].type == "response.delta"
    assert mapped.emitted_events[0].text == "hello"


def test_map_stream_event_collects_agent_summary_metadata() -> None:
    mapped = map_stream_event(
        StreamEvent(
            event_type="agent_summary",
            data={
                "agent_name": "support_agent",
                "llm_profile": "retrieval_profile",
                "safe_flag": True,
            },
        ),
        trace_id="trace_1",
        session_id="session_1",
    )

    assert mapped.agent_name == "support_agent"
    assert mapped.llm_profile == "retrieval_profile"
    assert mapped.metadata_patch == {"safe_flag": True}


def test_map_stream_event_preserves_orchestration_error_details() -> None:
    raw_event = OrchestrationStreamEvent.error_event(
        trace_id="trace_1",
        session_id="session_1",
        error=AgentExecutionError("stream failed"),
    )

    mapped = map_stream_event(raw_event, trace_id="trace_1", session_id="session_1")

    assert mapped.should_stop is True
    assert mapped.terminal_error is not None
    assert mapped.emitted_events[0].type == "orchestration.error"