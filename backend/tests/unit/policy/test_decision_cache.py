from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.decision_cache import PolicyDecisionCache
from app.policy.settings import PolicyDecisionCacheSettings
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def _build_context(trace_id: str = "trace-1") -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        OrchestrationContext(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="hello",
                usecase="default_chat",
                trace_id=trace_id,
            ),
            llm=FakeLLMGateway(),
            memory=FakeMemoryGateway(),
            state=FakeWorkflowStateStore(),
            tools=FakeToolGateway(),
            trace=FakeTraceStore(),
            policy=cast(object, SimpleNamespace()),
            config=FakeConfigurationView({}),
            runtime_metadata={"strategy_name": "direct_agent", "agent_name": "support_agent"},
        ),
    )


def test_decision_cache_reuses_safe_decision_for_same_turn() -> None:
    cache = PolicyDecisionCache(
        PolicyDecisionCacheSettings(enabled=True, ttl_seconds=30, max_entries=8)
    )
    request = PolicyRequest(
        action="tool.execute",
        component="app.tools.gateway",
        resource="billing.charge",
        scope={"user_id": "user-1", "session_id": "session-1", "usecase_name": "default_chat"},
        metadata={
            "tool_name": "billing.charge",
            "tool_safety_level": "write",
            "allowed_usecases": ["default_chat"],
        },
    )
    decision = PolicyDecision.allow(
        reason_code="policy.tool.allowed",
        metadata={"rule": "tool_access", "policy_profile": "default"},
    )
    context = _build_context()

    cache.put(request, context, profile_name="default", decision=decision)
    cached = cache.get(request, context, profile_name="default")

    assert cached is not None
    assert cached.reason_code == "policy.tool.allowed"
    assert cached.metadata == {"rule": "tool_access", "policy_profile": "default"}
    assert cached.actor is None
    assert cached.scope is None


def test_decision_cache_is_scoped_to_trace_id() -> None:
    cache = PolicyDecisionCache(
        PolicyDecisionCacheSettings(enabled=True, ttl_seconds=30, max_entries=8)
    )
    request = PolicyRequest(
        action="llm.complete",
        component="app.llm.gateway",
        resource="local_reasoning",
        scope={"user_id": "user-1", "session_id": "session-1", "usecase_name": "default_chat"},
        metadata={},
    )
    decision = PolicyDecision.allow(
        reason_code="policy.llm.allowed",
        metadata={"rule": "llm_access", "policy_profile": "default"},
    )

    cache.put(request, _build_context("trace-1"), profile_name="default", decision=decision)

    assert cache.get(request, _build_context("trace-2"), profile_name="default") is None