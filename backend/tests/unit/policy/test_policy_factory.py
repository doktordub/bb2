from __future__ import annotations

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyRequest
from app.policy.factory import build_policy_runtime
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {"strategy": "direct_agent", "fallback_strategy": "direct_agent"},
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
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
                        "allowed_agents": ["support_agent"],
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


async def test_policy_factory_builds_service_over_shared_engine() -> None:
    config = build_config()
    runtime = build_policy_runtime(config)
    context = OrchestrationContext(
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
        policy=runtime.service,
        config=config,
        runtime_metadata={
            "usecase_name": "default_chat",
            "strategy_name": "direct_agent",
            "agent_name": "support_agent",
        },
    )

    decision = await runtime.service.evaluate(
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

    assert runtime.service.engine is runtime.engine
    assert runtime.engine.registry is runtime.registry
    assert decision.allowed is True
    assert decision.metadata["rule"] == "strategy_access"