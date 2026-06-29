from __future__ import annotations

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMProviderTimeoutError
from app.testing.fakes import FakeTraceStore
from tests.unit.llm.support import base_config, build_context, build_gateway, build_registry
from app.llm.providers import FakeLLMProviderAdapter


async def test_gateway_retries_then_falls_back_for_retryable_errors() -> None:
    config = base_config()
    trace_store = FakeTraceStore()
    registry = build_registry(
        config,
        primary_adapter=FakeLLMProviderAdapter(
            name="primary_provider",
            complete_errors=[
                LLMProviderTimeoutError("timeout 1"),
                LLMProviderTimeoutError("timeout 2"),
            ],
        ),
        fallback_adapter=FakeLLMProviderAdapter(name="fallback_provider", response_text="fallback answer"),
    )
    gateway = build_gateway(config, registry=registry)
    context = build_context(config, trace_store=trace_store)

    response = await gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="hello world")]),
        context,
    )

    assert response.text == "fallback answer"
    assert response.profile == "fallback_profile"
    assert len(registry.get("primary_provider").calls) == 2
    assert len(registry.get("fallback_provider").calls) == 1
    event_names = [event.resolved_event_name for event in trace_store.events]
    assert "llm_retry_scheduled" in event_names
    assert "llm_fallback_selected" in event_names