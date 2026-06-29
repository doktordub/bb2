from __future__ import annotations

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyRequest
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_config(*, allowed_agents: list[str] | None = None, strategy_enabled: bool = True) -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": strategy_enabled,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": allowed_agents or ["support_agent"],
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                }
            },
            "policy": {
                "default_profile": "default",
                "profiles": {
                    "default": {
                        "deny_unknown_tools": True,
                        "deny_unknown_llm_profiles": True,
                        "require_memory_scope": True,
                        "allow_memory_writes": False,
                    }
                },
            },
        }
    )


def build_context(config: FakeConfigurationView) -> OrchestrationContext:
    policy = DefaultPolicyService(config)
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello",
            usecase="default_chat",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=policy,
        config=config,
        runtime_metadata={
            "usecase_name": "default_chat",
            "strategy_name": "direct_agent",
            "agent_name": "support_agent",
        },
    )


async def test_strategy_policy_allows_configured_strategy_usecase_and_agent() -> None:
    config = build_config()
    service = DefaultPolicyService(config)
    context = build_context(config)

    decision = await service.evaluate(
        PolicyRequest(
            action="orchestration.run_strategy",
            component="orchestration.runtime",
            resource="direct_agent",
            scope={
                "usecase_name": "default_chat",
                "strategy_name": "direct_agent",
                "agent_name": "support_agent",
            },
        ),
        context,
    )

    assert decision.allowed is True
    assert decision.metadata["resource"] == "direct_agent"


async def test_strategy_policy_denies_disabled_or_unauthorized_strategy_routes() -> None:
    disabled_config = build_config(strategy_enabled=False)
    disabled_service = DefaultPolicyService(disabled_config)
    disabled_context = build_context(disabled_config)

    disabled_decision = await disabled_service.evaluate(
        PolicyRequest(
            action="orchestration.run_strategy",
            component="orchestration.runtime",
            resource="direct_agent",
            scope={
                "usecase_name": "default_chat",
                "strategy_name": "direct_agent",
                "agent_name": "support_agent",
            },
        ),
        disabled_context,
    )

    assert disabled_decision.allowed is False
    assert "disabled" in (disabled_decision.reason or "")

    restricted_config = build_config(allowed_agents=["other_agent"])
    restricted_service = DefaultPolicyService(restricted_config)
    restricted_context = build_context(restricted_config)

    restricted_decision = await restricted_service.evaluate(
        PolicyRequest(
            action="orchestration.run_strategy",
            component="orchestration.runtime",
            resource="direct_agent",
            scope={
                "usecase_name": "default_chat",
                "strategy_name": "direct_agent",
                "agent_name": "support_agent",
            },
        ),
        restricted_context,
    )

    assert restricted_decision.allowed is False
    assert "not allowed" in (restricted_decision.reason or "")