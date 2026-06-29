from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.settings import PolicyProfileSettings, PolicyTraceSettings
from app.policy.trace_policy import (
    build_trace_policy_request,
    evaluate_trace_request,
    infer_trace_payload_category,
)
from app.testing.fakes import FakeConfigurationView


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="hello",
                usecase="default_chat",
                trace_id="trace-1",
            ),
            runtime_metadata={},
            config=FakeConfigurationView({}),
        ),
    )


def test_trace_payload_category_detects_prompt_text() -> None:
    assert infer_trace_payload_category({"prompt": "secret"}) == "raw_prompt"


@pytest.mark.asyncio
async def test_trace_policy_denies_raw_prompt_payloads_by_default() -> None:
    context = _build_context()
    request = build_trace_policy_request(
        trace_id="trace-1",
        session_id="session-1",
        user_id="user-1",
        usecase_name="default_chat",
        event_name="llm_call_started",
        component="app.llm.gateway",
        payload={"prompt": "secret prompt"},
        payload_category="raw_prompt",
    )

    decision = await evaluate_trace_request(
        request,
        context,
        PolicyProfileSettings(name="default", trace=PolicyTraceSettings()),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.trace.raw_payload_denied"


@pytest.mark.asyncio
async def test_trace_policy_allows_safe_summary_payload() -> None:
    context = _build_context()
    request = build_trace_policy_request(
        trace_id="trace-1",
        session_id="session-1",
        user_id="user-1",
        usecase_name="default_chat",
        event_name="health_checked",
        component="api.health",
        payload={"status": "ok"},
        payload_category="safe_summary",
    )

    decision = await evaluate_trace_request(
        request,
        context,
        PolicyProfileSettings(name="default"),
    )

    assert decision is not None
    assert decision.decision == "allow"
    assert decision.reason_code == "policy.trace.allowed"