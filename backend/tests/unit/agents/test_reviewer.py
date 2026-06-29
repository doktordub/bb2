from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.plugins.reviewer import ReviewerAgent
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


def build_context(*, response_text: str) -> tuple[OrchestrationContext, FakeLLMGateway, FakeTraceStore]:
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    trace_store = FakeTraceStore()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Review this proposed phase summary for gaps.",
            usecase="default_chat",
            trace_id="trace_reviewer",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=trace_store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "bounded_planner", "llm_profile": "review_profile"},
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, trace_store


@pytest.mark.asyncio
async def test_reviewer_returns_safe_review_result() -> None:
    context, llm, trace_store = build_context(
        response_text=(
            '{"passed": false, "score": 0.4, '
            '"findings": ["Missing the runtime migration dependency.", "Needs a validation command."], '
            '"suggested_revision": "Mention the runtime migration handoff and the focused pytest gate."}'
        )
    )
    agent = ReviewerAgent(name="reviewer")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=180, max_llm_calls=1)
    agent.context_policy = SimpleNamespace(max_context_items=2, max_context_bytes=300)

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        context_items=(
            PromptSection(title="Candidate answer", body="Phase 6 adds agents but omits validation details."),
        ),
        constraints=("Check completeness.", "Check that validation is specific."),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer is None
    assert result.review is not None
    assert result.review.passed is False
    assert result.review.score == 0.4
    assert result.review.findings == (
        "Missing the runtime migration dependency.",
        "Needs a validation command.",
    )
    assert result.review.suggested_revision == "Mention the runtime migration handoff and the focused pytest gate."
    assert result.metadata["review_passed"] is False
    assert llm.requests[0].profile == "review_profile"
    assert llm.requests[0].response_format is not None
    assert "agent_review_completed" in [event.resolved_event_name for event in trace_store.events]


@pytest.mark.asyncio
async def test_reviewer_limits_findings_and_normalizes_score_scale() -> None:
    context, _, _ = build_context(
        response_text=(
            '{"passed": true, "score": 8, "findings": ['
            '"Finding one", "Finding two", "Finding three", "Finding four", "Finding five", "Finding six"'
            ']}'
        )
    )
    agent = ReviewerAgent(name="reviewer")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=180, max_llm_calls=1)
    agent.context_policy = SimpleNamespace(max_context_items=2, max_context_bytes=300)

    request = build_run_request_from_context(context, agent_name=agent.name)

    result = await agent.run(request=request, context=context)

    assert result.review is not None
    assert result.review.score == 0.8
    assert len(result.review.findings) == 5
    assert result.warnings[0].code == "review_findings_limited"