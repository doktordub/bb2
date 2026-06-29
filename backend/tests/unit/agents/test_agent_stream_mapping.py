from __future__ import annotations

from app.agents.models import AgentRunResult
from app.agents.stream_mapping import build_completed_event, map_llm_stream_event
from app.contracts.llm import LLMErrorDetail, LLMStreamEvent, LLMTokenUsage


def test_map_llm_delta_to_agent_stream_event() -> None:
    event = map_llm_stream_event(
        "assistant",
        LLMStreamEvent.delta(
            text="hello",
            profile="reasoning",
            provider="fake_provider",
            model="fake_model",
        ),
    )

    assert event is not None
    assert event.type == "agent.llm.delta"
    assert event.agent_name == "assistant"
    assert event.text == "hello"
    assert event.metadata["profile"] == "reasoning"
    assert event.metadata["provider"] == "fake_provider"


def test_map_llm_error_to_agent_failed_event() -> None:
    event = map_llm_stream_event(
        "assistant",
        LLMStreamEvent(
            type="error",
            error=LLMErrorDetail(
                type="rate_limit",
                code="rate_limited",
                message="retry later",
                retryable=True,
            ),
        ),
    )

    assert event is not None
    assert event.type == "agent.failed"
    assert event.error is not None
    assert event.error.code == "rate_limited"
    assert event.error.retryable is True


def test_build_completed_event_preserves_structured_result() -> None:
    result = AgentRunResult(status="completed", answer="final answer", agent_name="assistant")

    event = build_completed_event(
        "assistant",
        result=result,
        metadata={
            "finish_reason": "completed",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
            },
        },
    )

    assert event.type == "agent.completed"
    assert event.result == result
    assert event.metadata["finish_reason"] == "completed"


def test_map_llm_completed_to_safe_agent_event() -> None:
    event = map_llm_stream_event(
        "assistant",
        LLMStreamEvent.completed(
            profile="reasoning",
            provider="fake_provider",
            model="fake_model",
            finish_reason="completed",
            usage=LLMTokenUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        ),
    )

    assert event is not None
    assert event.type == "agent.llm.completed"
    assert event.metadata["usage_counts"] == {
        "input": 1,
        "output": 2,
        "total": 3,
    }