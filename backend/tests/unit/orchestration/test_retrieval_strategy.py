from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.memory import MemoryResult
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import OrchestrationRuntimeContext
from app.orchestration.strategies.retrieval_augmented import RetrievalAugmentedStrategy
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "retrieval_augmented",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_chat"],
                        "llm_profile": "retrieval_profile",
                        "memory_enabled": True,
                        "memory": {
                            "default_limit": 2,
                            "include_document_chunks": True,
                            "include_user_memory": True,
                        },
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_chat"],
                    },
                },
                "usecases": {
                    "document_chat": {
                        "enabled": True,
                        "strategy": "retrieval_augmented",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "retrieval_profile",
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 2,
                        },
                        "tools": {"enabled": False, "allowed_tools": []},
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
            "llm": {"defaults": {"profile": "gateway_default"}},
            "memory": {"enabled": True},
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    llm: FakeLLMGateway,
    memory: FakeMemoryGateway,
    policy: FakePolicyService,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["retrieval_augmented"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the architecture",
            usecase="document_chat",
            trace_id="trace_1",
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=policy,
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "retrieval_augmented",
            "llm_profile": "retrieval_profile",
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
    )


@pytest.mark.asyncio
async def test_retrieval_strategy_searches_memory_and_returns_safe_summary() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="grounded answer")
    memory = FakeMemoryGateway(
        results=[
            MemoryResult(
                memory_id="memory_1",
                text="The backend orchestration layer routes through a strategy registry.",
                memory_type="document_chunk",
                source_id="architecture.md",
            )
        ]
    )
    policy = FakePolicyService()
    context = build_context(config, llm=llm, memory=memory, policy=policy)

    result = await RetrievalAugmentedStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "grounded answer"
    assert result.strategy_name == "retrieval_augmented"
    assert result.llm_profile == "retrieval_profile"
    assert len(memory.search_requests) == 1
    assert memory.search_requests[0].scope.project_id == "project_1"
    assert memory.search_requests[0].scope.user_id is None
    assert memory.search_requests[0].scope.session_id is None
    assert memory.search_requests[0].scope.agent_name is None
    assert memory.search_requests[0].scope.usecase is None
    assert llm.requests[0].profile == "retrieval_profile"
    assert "Retrieved context:" in llm.requests[0].messages[0].content
    assert [step["step_type"] for step in result.metadata["steps"]] == ["memory_search", "agent"]
    assert result.metadata["memory_searches"][0]["result_count"] == 1
    assert "strategy registry" not in str(result.metadata)
    assert [request.action for request in policy.requests] == ["memory.search", "agent.invoke"]
    assert policy.requests[0].scope["memory_scope"] == "project"
    assert policy.requests[0].scope["project_id"] == "project_1"
    assert policy.requests[0].scope["usecase"] == "document_chat"