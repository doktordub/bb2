from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.fallback_policy import build_fallback_policy_request, evaluate_fallback_request
from app.policy.settings import PolicyFallbackSettings, PolicyProfileSettings
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
            policy=None,
        ),
    )


@pytest.mark.asyncio
async def test_fallback_policy_denies_after_policy_denial() -> None:
    context = _build_context()
    request = build_fallback_policy_request(
        context=context,
        failed_strategy="direct_agent",
        fallback_strategy="fallback_answer",
        failure_type="strategy_policy_denied",
        policy_denied=True,
        side_effect_may_have_started=False,
        response_started=False,
    )

    decision = await evaluate_fallback_request(
        request,
        context,
        PolicyProfileSettings(name="default", fallback=PolicyFallbackSettings()),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.fallback.after_denial_denied"


@pytest.mark.asyncio
async def test_fallback_policy_allows_configured_degradable_failure() -> None:
    context = _build_context()
    request = build_fallback_policy_request(
        context=context,
        failed_strategy="direct_agent",
        fallback_strategy="fallback_answer",
        failure_type="dependency_unavailable",
        policy_denied=False,
        side_effect_may_have_started=False,
        response_started=False,
    )

    decision = await evaluate_fallback_request(
        request,
        context,
        PolicyProfileSettings(
            name="default",
            fallback=PolicyFallbackSettings(allowed_strategies=("fallback_answer",)),
        ),
    )

    assert decision is not None
    assert decision.decision == "allow"
    assert decision.reason_code == "policy.fallback.allowed"