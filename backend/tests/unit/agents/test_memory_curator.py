from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.plugins.memory_curator import MemoryCuratorAgent
from app.agents.result_builder import build_run_request_from_context
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
) -> tuple[OrchestrationContext, FakeLLMGateway, FakeMemoryGateway, FakeTraceStore]:
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    memory = FakeMemoryGateway()
    trace_store = FakeTraceStore()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Remember that the project root is backend/.",
            usecase="memory_capture",
            trace_id="trace_memory_curator",
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=FakeToolGateway(),
        trace=trace_store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "memory_update", "llm_profile": "memory_profile"},
        runtime=OrchestrationRuntimeContext(
            request_id="request_memory_curator",
            trace_id="trace_memory_curator",
            session_id="session_1",
            user_id="user_1",
            project_id="project_1",
        ),
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, memory, trace_store


@pytest.mark.asyncio
async def test_memory_curator_returns_bounded_candidates_without_writing_memory() -> None:
    context, llm, memory, trace_store = build_context(
        response_text=(
            '{"memory_candidates": ['
            '{"text": "Project root is backend/.", "memory_type": "project_fact", "scope": "project"}, '
            '{"text": "User prefers concise updates.", "memory_type": "preference", "scope": "user"}, '
            '{"text": "Extra candidate that should be truncated by the limit.", "memory_type": "user_fact", "scope": "user"}'
            ']}'
        )
    )
    agent = MemoryCuratorAgent(name="memory_curator")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=120,
        max_llm_calls=1,
        max_memory_candidates=2,
    )
    agent.context_policy = SimpleNamespace(max_context_items=2, max_context_bytes=300)
    agent.allowed_memory_scopes = ("project", "user")

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        context_items=(
            PromptSection(title="Turn summary", body="The user explicitly asked to remember the project root."),
        ),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer is None
    assert len(result.memory_candidates) == 2
    assert result.memory_candidates[0].scope == "project"
    assert result.memory_candidates[1].scope == "user"
    assert result.metadata["candidate_count"] == 2
    assert result.warnings[0].code == "memory_candidate_limit_reached"
    assert llm.requests[0].profile == "memory_profile"
    assert llm.requests[0].response_format is not None
    assert memory.writes == []
    assert "agent_memory_candidate_created" in [event.resolved_event_name for event in trace_store.events]


@pytest.mark.asyncio
async def test_memory_curator_skips_disallowed_scopes_with_safe_warning() -> None:
    context, _, _, _ = build_context(
        response_text=(
            '{"memory_candidates": ['
            '{"text": "Temporary session note.", "memory_type": "user_fact", "scope": "session"}, '
            '{"text": "Project language is Python.", "memory_type": "project_fact", "scope": "project"}'
            ']}'
        )
    )
    agent = MemoryCuratorAgent(name="memory_curator")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(
        max_output_chars=120,
        max_llm_calls=1,
        max_memory_candidates=3,
    )
    agent.context_policy = SimpleNamespace(max_context_items=2, max_context_bytes=300)
    agent.allowed_memory_scopes = ("project",)

    request = build_run_request_from_context(context, agent_name=agent.name)

    result = await agent.run(request=request, context=context)

    assert len(result.memory_candidates) == 1
    assert result.memory_candidates[0].text == "Project language is Python."
    assert result.warnings[0].code == "memory_candidate_skipped"