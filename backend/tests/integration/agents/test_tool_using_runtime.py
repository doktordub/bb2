from __future__ import annotations

import pytest

from app.agents.registry import DefaultAgentRegistry
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


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "agents": {
                "defaults": {
                    "enabled": True,
                    "stream_llm_deltas": False,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": True,
                    "known_prompt_profiles": ["tool_using_v1"],
                    "max_output_chars": 12000,
                    "max_llm_calls": 1,
                    "max_prompt_context_bytes": 4000,
                    "max_tool_intents": 2,
                },
                "plugins": {
                    "support_agent": {
                        "enabled": True,
                        "type": "tool_using",
                        "display_name": "Tool Agent",
                        "description": "Produces logical tool intents.",
                        "llm_profile": "agent_profile",
                        "prompt_profile": "tool_using_v1",
                        "capabilities": {
                            "answer": True,
                            "stream": True,
                            "memory_read": False,
                            "memory_write": False,
                            "tool_intents": True,
                            "tool_execute": False,
                            "self_managed_memory": False,
                            "self_managed_tools": False,
                        },
                        "allowed_tool_intents": ["documents_search"],
                    }
                },
            }
        }
    )


def build_context(*, response_text: str) -> tuple[OrchestrationContext, FakeLLMGateway, FakeToolGateway, FakeTraceStore]:
    trace_store = FakeTraceStore()
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    tools = FakeToolGateway()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Find architecture notes.",
            usecase="default_chat",
            trace_id="trace_tool_runtime",
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
    return context, llm, tools, trace_store


@pytest.mark.asyncio
async def test_registry_builds_and_runs_builtin_tool_using_agent_without_executing_tools() -> None:
    config = build_config()
    registry = DefaultAgentRegistry.from_config(config)
    agent = registry.resolve("support_agent")
    context, llm, tools, trace_store = build_context(
        response_text=(
            '{"kind": "tool_intent", "tool_name": "documents_search", '
            '"arguments": {"query": "architecture notes", "limit": 3}}'
        )
    )

    request = build_run_request_from_context(
        context,
        agent_name="support_agent",
        available_tools=("documents_search",),
    )
    result = await agent.run(request=request, context=context)

    assert len(result.tool_intents) == 1
    assert result.tool_intents[0].tool_name == "documents_search"
    assert tools.calls == []
    assert getattr(llm.requests[0].response_format, "type", None) == "json_object"
    assert "agent_tool_intent_created" in [event.resolved_event_name for event in trace_store.events]


@pytest.mark.asyncio
async def test_builtin_tool_using_agent_returns_final_answer_after_tool_context() -> None:
    config = build_config()
    agent = DefaultAgentRegistry.from_config(config).resolve("support_agent")
    context, _, tools, _ = build_context(
        response_text='{"kind": "final_answer", "answer": "Here is the safe tool summary."}'
    )

    request = build_run_request_from_context(
        context,
        agent_name="support_agent",
        available_tools=("documents_search",),
        tool_context=(
            PromptSection(
                title="Tool result",
                body="The tool found architecture notes.",
            ),
        ),
    )
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the safe tool summary."
    assert result.tool_intents == ()
    assert tools.calls == []