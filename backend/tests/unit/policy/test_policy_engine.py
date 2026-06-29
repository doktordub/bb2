from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.engine import DefaultPolicyEngine
from app.policy.registry import PolicyRegistry
from app.policy.rule import PolicyRule
from app.policy.rule_evaluator import CallbackPolicyRuleEvaluator
from app.policy.settings import PolicyProfileSettings, PolicySettings
from app.testing.fakes import FakeConfigurationView


def _build_context(config: FakeConfigurationView) -> OrchestrationContext:
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
            runtime_metadata={"strategy_name": "direct_agent", "agent_name": "support_agent"},
            config=config,
        ),
    )


@pytest.mark.asyncio
async def test_policy_engine_uses_explicit_precedence_over_evaluator_order() -> None:
    config = FakeConfigurationView({"policy": {"default_profile": "default"}})
    settings = PolicySettings(
        default_profile="default",
        profiles={"default": PolicyProfileSettings(name="default", default_decision="deny")},
    )
    registry = PolicyRegistry(
        (
            CallbackPolicyRuleEvaluator(
                rule=PolicyRule(name="allow_first", actions=("tool.execute",), priority=10),
                callback=lambda request, context, profile, runtime_config: PolicyDecision.allow(
                    reason="allowed",
                    reason_code="policy.test.allow",
                ),
            ),
            CallbackPolicyRuleEvaluator(
                rule=PolicyRule(name="approval_second", actions=("tool.execute",), priority=20),
                callback=lambda request, context, profile, runtime_config: PolicyDecision.approval_required(
                    reason="approval",
                    reason_code="policy.test.approval",
                ),
            ),
            CallbackPolicyRuleEvaluator(
                rule=PolicyRule(name="deny_last", actions=("tool.execute",), priority=30),
                callback=lambda request, context, profile, runtime_config: PolicyDecision.deny(
                    reason="denied",
                    reason_code="policy.test.deny",
                ),
            ),
        )
    )
    engine = DefaultPolicyEngine(config=config, settings=settings, registry=registry)

    decision = await engine.evaluate(
        PolicyRequest(
            action="tool.execute",
            component="app.tools.gateway",
            resource="documents.search",
        ),
        _build_context(config),
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.test.deny"
    assert decision.metadata["rule"] == "deny_last"


@pytest.mark.asyncio
async def test_policy_engine_defaults_to_profile_decision_when_no_rule_matches() -> None:
    config = FakeConfigurationView({"policy": {"default_profile": "default"}})
    settings = PolicySettings(
        default_profile="default",
        profiles={"default": PolicyProfileSettings(name="default", default_decision="deny")},
    )
    engine = DefaultPolicyEngine(config=config, settings=settings, registry=PolicyRegistry())

    decision = await engine.evaluate(
        PolicyRequest(
            action="health.read",
            component="app.api.routes_health",
        ),
        _build_context(config),
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.default_deny"