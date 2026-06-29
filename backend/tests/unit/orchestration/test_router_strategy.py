from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.tools import ToolDefinition, ToolExecutionResult, ToolResultContent, ToolResultSummary
from app.orchestration.strategy_factory import build_strategy_registry
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import OrchestrationRuntimeContext
from app.orchestration.strategies.router import RouterStrategy
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_config(*, use_llm_classifier: bool = False) -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "router",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 2,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "router": {
                        "enabled": True,
                        "type": "router",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["auto"],
                        "llm_profile": "router_profile",
                        "candidate_strategies": [
                            "direct_agent",
                            "retrieval_augmented",
                            "tool_assisted",
                        ],
                        "metadata": {"use_llm_classifier": use_llm_classifier},
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["auto"],
                        "llm_profile": "direct_profile",
                    },
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["auto"],
                        "llm_profile": "retrieval_profile",
                        "memory_enabled": True,
                        "memory": {
                            "default_limit": 2,
                            "include_document_chunks": True,
                            "include_user_memory": True,
                        },
                    },
                    "tool_assisted": {
                        "enabled": True,
                        "type": "tool_assisted",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["auto"],
                        "llm_profile": "tool_profile",
                        "tools_enabled": True,
                        "tools": {"allowed_tools": ["documents.search"], "max_calls": 2},
                    },
                },
                "usecases": {
                    "auto": {
                        "enabled": True,
                        "strategy": "router",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "router_profile",
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 2,
                        },
                        "tools": {"enabled": True, "allowed_tools": ["documents.search"]},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["documents.search"],
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
            "memory": {"enabled": True},
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    message: str,
    llm: FakeLLMGateway,
    memory: FakeMemoryGateway,
    tools: FakeToolGateway,
    policy: FakePolicyService | None = None,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["router"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message=message,
            usecase="auto",
            trace_id="trace_1",
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=tools,
        trace=FakeTraceStore(),
        policy=policy or FakePolicyService(),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "router",
            "llm_profile": "router_profile",
        },
        runtime=OrchestrationRuntimeContext(
            request_id="request_1",
            trace_id="trace_1",
            session_id="session_1",
            user_id="user_1",
            project_id="project_1",
        ),
        settings=settings,
        strategy_settings=strategy_settings,
        limits=limits,
        metadata={"strategy_registry": build_strategy_registry(config)},
    )


@pytest.mark.asyncio
async def test_router_strategy_prefers_tool_assisted_for_tool_prefixed_messages() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="router tool answer")
    tools = FakeToolGateway(
        tools=[ToolDefinition(name="documents.search", description="Search documents")],
        execution_results={
            "documents.search": ToolExecutionResult(
                tool_name="documents.search",
                status="completed",
                content=[ToolResultContent(type="text", text="Found architecture")],
                summary=ToolResultSummary(safe_message="Found architecture"),
            )
        },
    )
    context = build_context(
        config,
        message="tool: architecture",
        llm=llm,
        memory=FakeMemoryGateway(),
        tools=tools,
    )

    result = await RouterStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.strategy_name == "tool_assisted"
    assert result.metadata["routed_by"] == "router"
    assert result.metadata["route_reason"] == "tool_prefix"
    assert tools.calls[0].tool_name == "documents.search"


@pytest.mark.asyncio
async def test_router_strategy_can_use_llm_classifier_when_enabled() -> None:
    config = build_config(use_llm_classifier=True)
    llm = FakeLLMGateway(response_text="retrieval_augmented")
    memory = FakeMemoryGateway()
    context = build_context(
        config,
        message="Please research the architecture document",
        llm=llm,
        memory=memory,
        tools=FakeToolGateway(),
    )

    result = await RouterStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.strategy_name == "retrieval_augmented"
    assert result.metadata["route_reason"] == "llm_classifier"
    assert llm.requests[0].component == "orchestration.strategy.router"


@pytest.mark.asyncio
async def test_router_strategy_skips_policy_denied_candidate_and_uses_allowed_fallback() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="direct answer")
    policy = FakePolicyService(denied_resources={"tool_assisted"})
    tools = FakeToolGateway(
        tools=[ToolDefinition(name="documents.search", description="Search documents")]
    )
    context = build_context(
        config,
        message="tool: architecture",
        llm=llm,
        memory=FakeMemoryGateway(),
        tools=tools,
        policy=policy,
    )

    result = await RouterStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.strategy_name == "retrieval_augmented"
    assert result.metadata["route_reason"] == "retrieval_keyword"
    assert tools.calls == []