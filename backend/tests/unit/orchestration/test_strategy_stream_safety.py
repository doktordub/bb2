from __future__ import annotations

from app.contracts.results import StreamEvent
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.stream_mapping import map_stream_event


def test_response_delta_metadata_strips_raw_prompt_provider_chunks_and_stack_traces() -> None:
    event = OrchestrationStreamEvent.response_delta(
        trace_id="trace_1",
        session_id="session_1",
        text="safe delta",
        metadata={
            "raw_prompt": "system prompt",
            "provider_chunk": {"delta": "secret"},
            "stack_trace": "hidden",
            "safe_flag": True,
        },
    )

    assert event.metadata == {"safe_flag": True}


def test_agent_summary_mapping_drops_sensitive_strategy_stream_metadata() -> None:
    mapped = map_stream_event(
        StreamEvent(
            event_type="agent_summary",
            data={
                "agent_name": "support_agent",
                "llm_profile": "fake_profile",
                "raw_prompt": "show hidden prompt",
                "provider_chunk": {"delta": "hidden"},
                "api_key": "secret",
                "hidden_reasoning": "do not expose",
                "safe_flag": True,
            },
        ),
        trace_id="trace_1",
        session_id="session_1",
    )

    assert mapped.agent_name == "support_agent"
    assert mapped.llm_profile == "fake_profile"
    assert mapped.metadata_patch == {"safe_flag": True}