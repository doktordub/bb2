from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMBadRequestError, LLMUnsupportedCapabilityError
from app.testing.fakes import FakeTraceStore
from tests.unit.llm.support import base_config, build_context, build_gateway


async def test_gateway_complete_returns_normalized_response_and_health_metadata() -> None:
    config = base_config()
    gateway = build_gateway(config)
    context = build_context(config)

    response = await gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="hello world")]),
        context,
    )
    health = await gateway.health()
    profiles = await gateway.list_profiles()

    assert response.text == "primary answer"
    assert response.profile == "primary_profile"
    assert response.provider == "primary_provider"
    assert response.model == "primary-model"
    assert response.usage is not None
    assert health.status == "ok"
    assert health.default_profile == "primary_profile"
    assert [profile.name for profile in profiles][:2] == ["primary_profile", "fallback_profile"]


async def test_gateway_complete_rejects_excessive_output_limit_without_mutating_request() -> None:
    config = base_config()
    gateway = build_gateway(config)
    context = build_context(config)
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="hello world")],
        max_output_tokens=64,
    )

    with pytest.raises(LLMBadRequestError, match="Requested output exceeds"):
        await gateway.complete(request, context)

    assert request.max_output_tokens == 64


async def test_gateway_complete_rejects_structured_output_when_profile_lacks_capability() -> None:
    config = base_config()
    assert isinstance(config["llm"], dict)
    assert isinstance(config["llm"]["profiles"], dict)
    config["llm"]["profiles"]["primary_profile"]["supports_json_schema"] = False
    gateway = build_gateway(config)
    context = build_context(config)

    with pytest.raises(LLMUnsupportedCapabilityError, match="structured output"):
        await gateway.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content="hello world")],
                response_format={"type": "json_schema", "json_schema": {"type": "object"}},
            ),
            context,
        )


async def test_gateway_complete_records_trace_events() -> None:
    config = base_config()
    trace_store = FakeTraceStore()
    gateway = build_gateway(config)
    context = build_context(config, trace_store=trace_store)

    await gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="hello world")]),
        context,
    )

    event_names = [event.resolved_event_name for event in trace_store.events]
    assert event_names == [
        "llm_profile_resolved",
        "llm_policy_checked",
        "llm_call_started",
        "llm_call_completed",
    ]