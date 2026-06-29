from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.plugins.general_assistant import GeneralAssistantAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.testing.fakes import FakeConfigurationView, FakeLLMGateway, FakeMemoryGateway, FakePolicyService, FakeToolGateway, FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def build_context(response_text: str = "general answer") -> tuple[OrchestrationContext, FakeLLMGateway, FakeMemoryGateway, FakeToolGateway]:
    llm = FakeLLMGateway(response_text=response_text)
    memory = FakeMemoryGateway()
    tools = FakeToolGateway()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="How does phase four work?",
            usecase="default_chat",
            trace_id="trace_general_assistant",
            metadata={},
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=tools,
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "direct_agent", "llm_profile": "usecase_profile"},
        observability=build_fake_trace_recorder(),
        metadata={"session_summary": "The session is focused on backend planning."},
    )
    return context, llm, memory, tools


@pytest.mark.asyncio
async def test_general_assistant_answers_through_llm_only() -> None:
    context, llm, memory, tools = build_context()
    agent = GeneralAssistantAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.prompt_profile = "general_assistant_v1"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "general answer"
    assert result.agent_name == "support_agent"
    assert result.llm_profile == "usecase_profile"
    assert result.usage is not None
    assert result.usage.llm_calls == 1
    assert memory.search_requests == []
    assert tools.calls == []

    messages = llm.requests[0].messages
    assert messages[0].role == "system"
    assert "backend general assistant" in str(messages[0].content).lower()
    assert "Session summary" in str(messages[1].content)
    assert "How does phase four work?" in str(messages[1].content)


@pytest.mark.asyncio
async def test_general_assistant_stream_emits_safe_final_result() -> None:
    context, _, _, _ = build_context(response_text="streamed general answer")
    agent = GeneralAssistantAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.prompt_profile = "general_assistant_v1"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    events = []
    async for event in agent.stream(request=request, context=context):
        events.append(event)

    assert events[0].type == "agent.started"
    assert events[-1].type == "agent.completed"
    assert events[-1].result is not None
    assert events[-1].result.answer == "streamed general answer"