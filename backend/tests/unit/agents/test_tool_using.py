from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.errors import AgentToolIntentError
from app.agents.plugins.tool_using import ToolUsingAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMMessage, LLMToolCall
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def build_context(
    *,
    response_text: str,
    tool_calls: tuple[LLMToolCall | dict[str, object], ...] = (),
    config: FakeConfigurationView | None = None,
) -> tuple[OrchestrationContext, FakeLLMGateway, FakeToolGateway]:
    llm = FakeLLMGateway(
        response_text=response_text,
        default_profile="gateway_default",
        tool_calls=tool_calls,
    )
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
        config=config
        or FakeConfigurationView(
            {
                "llm": {
                    "profiles": {
                        "tool_profile": {
                            "supports_tool_calling": True,
                        }
                    }
                }
            }
        ),
        runtime_metadata={"strategy_name": "tool_assisted", "llm_profile": "tool_profile"},
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, tools


@pytest.mark.asyncio
async def test_tool_using_returns_validated_logical_tool_intent_without_executing_tool() -> None:
    context, llm, tools = build_context(
        response_text="",
        tool_calls=(
            {
                "id": "call_documents_search_1",
                "function": {
                    "name": "documents_search",
                    "arguments": '{"query": "architecture notes", "limit": 2}',
                },
            },
        ),
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
    assert result.metadata["tool_calling_mode"] == "native"
    assert llm.requests[0].profile == "tool_profile"
    assert llm.requests[0].response_format is None
    assert getattr(llm.requests[0].tool_choice, "type", None) == "auto"
    assert [tool.function.name for tool in llm.requests[0].tools] == ["documents_search"]
    assert tools.calls == []


@pytest.mark.asyncio
async def test_tool_using_returns_final_answer_from_native_tool_followup() -> None:
    context, _, tools = build_context(
        response_text="Here is the safe summary."
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
        llm_followup_messages=(
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_documents_search_1",
                        function={
                            "name": "documents_search",
                            "arguments": '{"query": "architecture notes", "limit": 2}',
                        },
                    )
                ],
            ),
            LLMMessage(
                role="tool",
                content="The indexed documents mention strategy registration.",
                tool_call_id="call_documents_search_1",
            ),
        ),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the safe summary."
    assert result.tool_intents == ()
    assert result.metadata["response_mode"] == "final_answer"
    assert result.metadata["tool_calling_mode"] == "followup"
    assert tools.calls == []


@pytest.mark.asyncio
async def test_tool_using_falls_back_to_prompt_only_json_when_profile_lacks_schema_support() -> None:
    context, llm, tools = build_context(
        response_text=(
            '{"kind": "tool_intent", "tool_name": "documents_search", '
            '"arguments": {"query": "weather in Dallas TX"}}'
        ),
        config=FakeConfigurationView(
            {
                "llm": {
                    "profiles": {
                        "tool_profile": {
                            "supports_tool_calling": False,
                            "supports_json_schema": False,
                        }
                    }
                }
            }
        ),
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
    assert llm.requests[0].tools == []
    assert llm.requests[0].metadata["tool_calling_fallback"] == "prompt_json"
    assert llm.requests[0].metadata["response_format_fallback"] == "prompt_only"
    assert tools.calls == []


@pytest.mark.asyncio
async def test_tool_using_rejects_unknown_logical_tool_names() -> None:
    context, _, _ = build_context(
        response_text="",
        tool_calls=(
            {
                "id": "call_unknown_1",
                "function": {
                    "name": "unknown_tool",
                    "arguments": '{"text": "hi"}',
                },
            },
        ),
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