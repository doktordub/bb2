from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.errors import AgentInputValidationError
from app.agents.factory import AgentFactory
from app.agents.plugins.project_agent import ProjectAgent
from app.agents.result_builder import build_run_request_from_context
from app.config.view import get_agents_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.models import OrchestrationRuntimeContext
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


def build_context(
    *,
    response_text: str,
    project_id: str | None = "project_1",
) -> tuple[OrchestrationContext, FakeLLMGateway, FakeToolGateway]:
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    tools = FakeToolGateway()
    trace_store = FakeTraceStore()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Inspect the backend architecture plan.",
            usecase="default_chat",
            trace_id="trace_project_agent",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=tools,
        trace=trace_store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "tool_assisted", "llm_profile": "project_profile"},
        runtime=OrchestrationRuntimeContext(
            request_id="request_project_agent",
            trace_id="trace_project_agent",
            session_id="session_1",
            user_id="user_1",
            project_id=project_id,
        ),
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, tools


def test_agent_factory_builds_builtin_project_agent() -> None:
    config = FakeConfigurationView(
        {
            "agents": {
                "defaults": {"strict_prompt_profile_validation": False},
                "plugins": {
                    "support_agent": {
                        "enabled": True,
                        "type": "project_agent",
                        "llm_profile": "project_profile",
                        "prompt_profile": "project_agent_v1",
                        "allowed_tool_intents": ["project_read_file"],
                        "allowed_memory_scopes": ["project"],
                        "capabilities": {
                            "answer": True,
                            "stream": True,
                            "memory_read": True,
                            "memory_write": False,
                            "tool_intents": True,
                            "tool_execute": False,
                        },
                    }
                },
            }
        }
    )
    settings = get_agents_settings(config)
    factory = AgentFactory(settings=settings)

    agent = factory.build(settings.plugins["support_agent"])

    assert isinstance(agent, ProjectAgent)
    assert agent.type == "project_agent"
    assert agent.metadata["built_in"] is True
    assert agent.metadata["mode"] == "project_scoped"


@pytest.mark.asyncio
async def test_project_agent_requires_project_scope() -> None:
    context, llm, _ = build_context(
        response_text='{"kind": "final_answer", "answer": "unused"}',
        project_id=None,
    )
    agent = ProjectAgent(name="project_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=400,
        max_llm_calls=1,
        max_prompt_context_bytes=800,
        max_tool_intents=2,
    )
    agent.context_policy = SimpleNamespace(max_context_items=2, max_context_bytes=300)
    agent.allowed_tool_intents = ("project_read_file",)

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("project_read_file",),
    )

    with pytest.raises(AgentInputValidationError):
        await agent.run(request=request, context=context)
    assert llm.requests == []


@pytest.mark.asyncio
async def test_project_agent_returns_project_scoped_tool_intent_without_executing_tools() -> None:
    context, llm, tools = build_context(
        response_text=(
            '{"kind": "tool_intent", "tool_name": "project_read_file", '
            '"arguments": {"path": "docs/backend-agents-architecture.md"}, '
            '"reason": "Need the referenced architecture details"}'
        )
    )
    agent = ProjectAgent(name="project_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=400,
        max_llm_calls=1,
        max_prompt_context_bytes=800,
        max_tool_intents=2,
    )
    agent.context_policy = SimpleNamespace(max_context_items=1, max_context_bytes=120)
    agent.allowed_tool_intents = ("project_read_file", "documents_search")

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("project_read_file", "documents_search"),
        context_items=(
            PromptSection(
                title="Architecture excerpt",
                body="Project agents should stay inside the active project scope.",
            ),
            PromptSection(
                title="Architecture excerpt",
                body="This second section should be dropped by the context limit.",
            ),
        ),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer is None
    assert len(result.tool_intents) == 1
    assert result.tool_intents[0].tool_name == "project_read_file"
    assert result.llm_profile == "project_profile"
    assert result.metadata["project_id_present"] is True
    assert result.metadata["project_context_count"] == 1
    assert llm.requests[0].profile == "project_profile"
    assert llm.requests[0].response_format is not None
    assert "active project scope" in str(llm.requests[0].messages[0].content).lower()
    assert tools.calls == []