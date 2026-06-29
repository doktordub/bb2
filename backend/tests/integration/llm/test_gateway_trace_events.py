from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from app.testing.fakes import FakeTraceStore
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view


@pytest.mark.asyncio
async def test_gateway_trace_events_stay_redacted_by_default() -> None:
    config = await load_config_view("llm_fake_basic.yaml")
    trace_store = FakeTraceStore()
    runtime = build_runtime_bundle(config)
    context = build_context(
        config,
        trace_store=trace_store,
        message="do not leak this prompt",
    )

    await runtime.gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="do not leak this prompt")]),
        context,
    )

    payloads = {event.resolved_event_name: dict(event.payload) for event in trace_store.events}
    assert payloads["llm_call_started"] == {}
    assert payloads["llm_call_completed"] == {}


@pytest.mark.asyncio
async def test_gateway_trace_capture_fixture_enables_prompt_and_completion_capture() -> None:
    config = await load_config_view("llm_trace_capture_enabled_local_only.yaml")
    trace_store = FakeTraceStore()
    runtime = build_runtime_bundle(config)
    context = build_context(
        config,
        trace_store=trace_store,
        message="capture this prompt",
    )

    await runtime.gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="capture this prompt")]),
        context,
    )

    payloads = {event.resolved_event_name: dict(event.payload) for event in trace_store.events}
    assert payloads["llm_call_started"]["messages"] == ["capture this prompt"]
    assert payloads["llm_call_completed"]["text"] == "traced fake response"