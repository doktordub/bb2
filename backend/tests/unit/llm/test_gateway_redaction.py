from __future__ import annotations

from app.contracts.llm import LLMMessage, LLMRequest
from app.testing.fakes import FakeTraceStore
from tests.unit.llm.support import base_config, build_context, build_gateway


async def test_gateway_trace_payloads_redact_prompts_and_completions_by_default() -> None:
    config = base_config(trace_payloads_enabled=True, trace_prompts=False, trace_completions=False)
    trace_store = FakeTraceStore()
    gateway = build_gateway(config)
    context = build_context(config, trace_store=trace_store)

    await gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="secret prompt text")],
            metadata={"api_key": "super-secret-key"},
        ),
        context,
    )

    started_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_started")
    completed_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_completed")

    assert "messages" not in started_event.payload
    assert started_event.payload["message_count"] == 1
    assert completed_event.payload["raw_id_present"] is True
    assert "text" not in completed_event.payload


async def test_gateway_trace_payloads_include_prompt_and_completion_when_enabled() -> None:
    config = base_config(trace_payloads_enabled=True, trace_prompts=True, trace_completions=True)
    trace_store = FakeTraceStore()
    gateway = build_gateway(config)
    context = build_context(config, trace_store=trace_store)

    await gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="visible prompt")]),
        context,
    )

    started_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_started")
    completed_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_completed")

    assert started_event.payload["messages"] == ["visible prompt"]
    assert completed_event.payload["text"] == "primary answer"