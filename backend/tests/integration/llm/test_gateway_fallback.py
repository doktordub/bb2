from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMProviderTimeoutError
from app.llm.providers import FakeLLMProviderAdapter
from app.testing.fakes import FakeTraceStore
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view


@pytest.mark.asyncio
async def test_gateway_uses_fallback_profile_after_retryable_primary_failures() -> None:
    config = await load_config_view("llm_fake_fallback.yaml")
    trace_store = FakeTraceStore()
    provider = FakeLLMProviderAdapter(
        name="fake_provider",
        response_text="fallback answer",
        complete_errors=[
            LLMProviderTimeoutError("timeout 1"),
            LLMProviderTimeoutError("timeout 2"),
            LLMProviderTimeoutError("timeout 3"),
        ],
    )
    runtime = build_runtime_bundle(config, provider_overrides={"fake_provider": provider})
    context = build_context(config, trace_store=trace_store)

    response = await runtime.gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="fallback integration")]),
        context,
    )

    assert response.text == "fallback answer"
    assert response.profile == "fake_backup"
    assert [call.request.profile_name for call in provider.calls] == [
        "fake_primary",
        "fake_primary",
        "fake_primary",
        "fake_backup",
    ]
    event_names = [event.resolved_event_name for event in trace_store.events]
    assert "llm_retry_scheduled" in event_names
    assert "llm_fallback_selected" in event_names