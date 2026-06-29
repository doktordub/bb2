from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.strategies.direct_agent import DirectAgentStrategy
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_config(*, memory_enabled: bool = False, tools_enabled: bool = False) -> FakeConfigurationView:
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
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "strategy_profile",
                        "memory_enabled": memory_enabled,
                        "tools_enabled": tools_enabled,
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "usecase_profile",
                        "memory": {"enabled": True},
                        "tools": {
                            "enabled": True,
                            "allowed_tools": ["documents.search"],
                        },
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "llm_profile": "agent_profile",
                    "allowed_tools": ["documents.search"],
                    "memory": {"search_enabled": True},
                }
            },
            "memory": {"enabled": True},
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    message: str,
    llm: FakeLLMGateway,
    memory: FakeMemoryGateway,
    tools: FakeToolGateway,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message=message,
            usecase="default_chat",
            trace_id="trace_1",
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=tools,
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "direct_agent",
            "usecase_name": "default_chat",
        },
        settings=settings,
        strategy_settings=settings.strategies["direct_agent"],
    )


@pytest.mark.asyncio
async def test_direct_agent_strategy_disables_memory_and_tools_until_strategy_enables_them() -> None:
    config = build_config(memory_enabled=False, tools_enabled=False)
    llm = FakeLLMGateway(response_text="direct answer")
    memory = FakeMemoryGateway()
    tools = FakeToolGateway()
    context = build_context(
        config,
        message="tool: architecture",
        llm=llm,
        memory=memory,
        tools=tools,
    )

    result = await DirectAgentStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "direct answer"
    assert result.llm_profile == "usecase_profile"
    assert llm.requests[0].profile == "usecase_profile"
    assert [step["step_type"] for step in result.metadata["steps"]] == ["agent"]
    assert memory.search_requests == []
    assert tools.calls == []


@pytest.mark.asyncio
async def test_direct_agent_strategy_stream_reuses_agent_run_path() -> None:
    config = build_config(memory_enabled=False, tools_enabled=False)
    llm = FakeLLMGateway(response_text="streamed direct answer")
    memory = FakeMemoryGateway()
    tools = FakeToolGateway()
    context = build_context(
        config,
        message="hello",
        llm=llm,
        memory=memory,
        tools=tools,
    )

    events = [
        event
        async for event in DirectAgentStrategy().stream(
            context=context,
            agents=[FakeAgent(name="support_agent")],
        )
    ]

    assert [event.type if hasattr(event, "type") else event.event_type for event in events] == [
        "response.delta",
        "agent_summary",
        "response.completed",
    ]
    assert events[0].text == "streamed direct answer"
    assert llm.requests[0].profile == "usecase_profile"