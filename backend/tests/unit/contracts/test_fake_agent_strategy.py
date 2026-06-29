from __future__ import annotations

from app.contracts.memory import MemoryScope, MemorySearchRequest
from app.contracts.context import OrchestrationContext, RequestContext
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeDirectStrategy,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_context(
    response_text: str = "fake response",
    *,
    config: FakeConfigurationView | None = None,
    memory: FakeMemoryGateway | None = None,
) -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Explain the contract slice",
            usecase="support",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(response_text=response_text),
        memory=memory or FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=config or FakeConfigurationView(),
        runtime_metadata={"strategy": "direct"},
    )


async def test_fake_agent_uses_llm_gateway_through_context() -> None:
    context = build_context(response_text="contract answer")
    agent = FakeAgent()

    result = await agent.run(context)

    assert result.answer == "contract answer"
    assert result.agent_name == "fake_agent"
    assert result.llm_profile == "fake_profile"
    assert len(agent.runs) == 1
    assert len(context.llm.requests) == 1
    assert context.llm.requests[0].component == "agent.fake_agent"
    assert context.llm.requests[0].messages[0].content == "Explain the contract slice"


async def test_fake_agent_uses_memory_gateway_when_enabled() -> None:
    memory = FakeMemoryGateway()
    context = build_context(
        response_text="memory answer",
        config=FakeConfigurationView(
            {
                "features": {"memory_enabled": True},
                "agents": {"fake_agent": {"memory": {"search_enabled": True}}},
            }
        ),
        memory=memory,
    )
    agent = FakeAgent()

    result = await agent.run(context)

    assert result.answer == "memory answer"
    assert result.metadata["memory_result_count"] == 0
    assert memory.search_requests == [
        MemorySearchRequest(text="Explain the contract slice", scope=MemoryScope())
    ]


async def test_fake_strategy_executes_agent_and_returns_normalized_result() -> None:
    context = build_context(response_text="strategy answer")
    agent = FakeAgent()
    strategy = FakeDirectStrategy()

    result = await strategy.run(context, [agent])

    assert result.answer == "strategy answer"
    assert result.session_id == "session_1"
    assert result.trace_id == "trace_1"
    assert result.agent_name == "fake_agent"
    assert result.strategy_name == "fake_direct_strategy"
    assert result.llm_profile == "fake_profile"
    assert strategy.agent_names == ["fake_agent"]
    assert strategy.contexts == [context]