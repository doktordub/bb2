from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.errors import AgentToolIntentError
from app.agents.plugins.tool_using import ToolUsingAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.prompt_inputs import PromptSection
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def build_context(*, response_text: str) -> tuple[OrchestrationContext, FakeLLMGateway, FakeToolGateway]:
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    tools = FakeToolGateway()
    trace_store = FakeTraceStore()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Find architecture notes",
            usecase="default_chat",
            trace_id="trace_tool_using",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=tools,
        trace=trace_store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "tool_assisted", "llm_profile": "tool_profile"},
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, tools


@pytest.mark.asyncio
async def test_tool_using_returns_validated_logical_tool_intent_without_executing_tool() -> None:
    context, llm, tools = build_context(
        response_text=(
            '{"kind": "tool_intent", "tool_name": "documents_search", '
            '"arguments": {"query": "architecture notes", "limit": 2}, '
            '"reason": "Need relevant documents"}'
        )
    )
    agent = ToolUsingAgent(name="tool_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=200,
        max_llm_calls=1,
        max_prompt_context_bytes=800,
        max_tool_intents=2,
    )
    agent.allowed_tool_intents = ("documents_search",)

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("documents_search",),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer is None
    assert len(result.tool_intents) == 1
    assert result.tool_intents[0].tool_name == "documents_search"
    assert result.tool_intents[0].arguments == {"query": "architecture notes", "limit": 2}
    assert result.metadata["response_mode"] == "tool_intents"
    assert llm.requests[0].profile == "tool_profile"
    assert llm.requests[0].response_format is not None
    assert getattr(llm.requests[0].response_format, "type", None) == "json_object"
    assert tools.calls == []


@pytest.mark.asyncio
async def test_tool_using_returns_final_answer_from_tool_context() -> None:
    context, _, tools = build_context(
        response_text='{"kind": "final_answer", "answer": "Here is the safe summary."}'
    )
    agent = ToolUsingAgent(name="tool_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=200,
        max_llm_calls=1,
        max_prompt_context_bytes=800,
        max_tool_intents=2,
    )
    agent.allowed_tool_intents = ("documents_search",)

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("documents_search",),
        tool_context=(
            PromptSection(
                title="Tool result",
                body="The indexed documents mention strategy registration.",
            ),
        ),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the safe summary."
    assert result.tool_intents == ()
    assert result.metadata["response_mode"] == "final_answer"
    assert tools.calls == []


@pytest.mark.asyncio
async def test_tool_using_falls_back_to_prompt_only_json_when_profile_lacks_schema_support() -> None:
    context, llm, tools = build_context(
        response_text=(
            '{"kind": "tool_intent", "tool_name": "documents_search", '
            '"arguments": {"query": "weather in Dallas TX"}}'
        )
    )
    context.config = FakeConfigurationView(
        {
            "llm": {
                "profiles": {
                    "tool_profile": {
                        "supports_json_schema": False,
                    }
                }
            }
        }
    )
    agent = ToolUsingAgent(name="tool_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=200,
        max_llm_calls=1,
        max_prompt_context_bytes=800,
        max_tool_intents=2,
    )
    agent.allowed_tool_intents = ("documents_search",)

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("documents_search",),
    )

    result = await agent.run(request=request, context=context)

    assert len(result.tool_intents) == 1
    assert llm.requests[0].response_format is None
    assert llm.requests[0].metadata["response_format_fallback"] == "prompt_only"
    assert tools.calls == []


@pytest.mark.asyncio
async def test_tool_using_rejects_unknown_logical_tool_names() -> None:
    context, _, _ = build_context(
        response_text='{"kind": "tool_intent", "tool_name": "unknown_tool", "arguments": {"text": "hi"}}'
    )
    agent = ToolUsingAgent(name="tool_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=200,
        max_llm_calls=1,
        max_prompt_context_bytes=800,
        max_tool_intents=2,
    )
    agent.allowed_tool_intents = ("documents_search",)

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("documents_search",),
    )

    with pytest.raises(AgentToolIntentError):
        await agent.run(request=request, context=context)