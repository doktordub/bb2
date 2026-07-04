from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.plugins.general_assistant import GeneralAssistantAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.models import ConversationMessage, OrchestrationRuntimeContext
from app.orchestration.state_delta import WorkflowStateSnapshot
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
        config=FakeConfigurationView(
            {
                "orchestration": {
                    "defaults": {
                        "conversation_context": {
                            "enabled": True,
                            "mode": "window",
                            "max_messages": 12,
                            "max_chars": 12000,
                            "include_assistant_messages": True,
                            "summary_threshold_messages": 24,
                            "summary_max_chars": 2000,
                        }
                    }
                }
            }
        ),
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
    assert messages[2].role == "user"
    assert "How does phase four work?" in str(messages[2].content)


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


def test_build_run_request_projects_prior_conversation_history_from_workflow_state() -> None:
    context, _, _, _ = build_context()
    context.state = WorkflowStateSnapshot(
        session_id="session_1",
        version=2,
        messages=[
            ConversationMessage(
                role="user",
                content="I am Bob",
                metadata={"request_id": "request-1", "turn_id": "request-1", "trace_id": "trace-1"},
            )
        ],
    )

    request = build_run_request_from_context(context, agent_name="support_agent")

    assert [message.content for message in request.conversation_history] == ["I am Bob"]
    assert request.metadata["conversation_history_turn_count"] == 1


@pytest.mark.asyncio
async def test_general_assistant_emits_prior_turns_as_chat_history_before_current_request() -> None:
    context, llm, _, _ = build_context(response_text="Bob")
    context.request.message = "What is my name?"
    context.state = WorkflowStateSnapshot(
        session_id="session_1",
        version=4,
        messages=[
            ConversationMessage(
                role="user",
                content="I am Bob",
                metadata={"request_id": "request-1", "turn_id": "request-1", "trace_id": "trace-1"},
            ),
            ConversationMessage(
                role="assistant",
                content="Nice to meet you, Bob.",
                metadata={"request_id": "request-1", "turn_id": "request-1", "trace_id": "trace-1"},
            ),
            ConversationMessage(
                role="user",
                content="What is my name?",
                metadata={
                    "request_id": "request-current",
                    "turn_id": "request-current",
                    "trace_id": "trace_general_assistant",
                },
            ),
        ],
    )
    context.runtime = OrchestrationRuntimeContext(
        request_id="request-current",
        trace_id="trace_general_assistant",
        session_id="session_1",
        user_id="user_1",
    )

    agent = GeneralAssistantAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.prompt_profile = "general_assistant_v1"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Bob"
    messages = llm.requests[0].messages
    assert [message.role for message in messages] == ["system", "user", "user", "assistant", "user"]
    assert "Session summary" in str(messages[1].content)
    assert messages[2].content == "I am Bob"
    assert messages[3].content == "Nice to meet you, Bob."
    assert "What is my name?" in str(messages[4].content)