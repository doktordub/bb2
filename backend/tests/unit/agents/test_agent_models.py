from __future__ import annotations

from app.agents.models import (
    AgentCapabilities,
    AgentHealthResult,
    AgentOutputItem,
    AgentReviewResult,
    AgentRunRequest,
    AgentRunResult,
    AgentUsageSummary,
    AgentWarning,
)
from app.agents.result_builder import build_run_request_from_context, to_legacy_agent_result
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.memory_intents import MemoryCandidate
from app.orchestration.prompt_inputs import PromptSection
from app.orchestration.tool_intents import ToolIntent
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_context(response_text: str = "structured answer") -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Explain the architecture slice",
            usecase="support",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(response_text=response_text),
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy": "direct_agent"},
    )


def test_agent_run_request_sanitizes_metadata_and_context_items() -> None:
    request = AgentRunRequest(
        trace_id="trace_1",
        session_id="session_1",
        user_id="user_1",
        project_id="project_1",
        usecase="support",
        message="Summarize the current architecture",
        context_items=(PromptSection(title="Context", body="bounded context"),),
        available_tools=("documents.search",),
        metadata={"safe": "ok", "raw_prompt": "blocked"},
    )

    assert request.available_tools == ("documents.search",)
    assert request.context_items[0].title == "Context"
    assert request.metadata == {"safe": "ok"}


def test_structured_result_adapts_to_legacy_result() -> None:
    structured = AgentRunResult(
        status="completed",
        answer="Here is the answer.",
        agent_name="general_assistant_agent",
        llm_profile="reasoning",
        tool_intents=(
            ToolIntent(
                tool_name="documents.search",
                arguments={"query": "architecture", "limit": 3},
                query="architecture",
                metadata={"status": "completed", "safe_message": "Search complete."},
            ),
        ),
        memory_candidates=(MemoryCandidate(text="User prefers architecture reviews."),),
        review=AgentReviewResult(status="completed", passed=True, findings=("Grounded.",)),
        usage=AgentUsageSummary(llm_calls=1, tool_calls=1, input_chars=10, output_chars=20),
        output_items=(
            AgentOutputItem(
                type="citation",
                text="Architecture excerpt",
                source_label="Architecture Doc",
                confidence=0.8,
            ),
        ),
        warnings=(AgentWarning(code="note", message="Safe warning."),),
        metadata={"safe": "ok", "raw_prompt": "blocked"},
    )

    legacy = to_legacy_agent_result(structured)

    assert legacy.answer == "Here is the answer."
    assert legacy.agent_name == "general_assistant_agent"
    assert legacy.tool_calls[0]["tool_name"] == "documents.search"
    assert legacy.tool_calls[0]["status"] == "completed"
    assert legacy.memory_updates[0]["text"] == "User prefers architecture reviews."
    assert legacy.citations[0]["source_label"] == "Architecture Doc"
    assert legacy.metadata["review"]["passed"] is True
    assert legacy.metadata["usage"]["llm_calls"] == 1
    assert "raw_prompt" not in legacy.metadata


async def test_fake_agent_supports_structured_run_and_health() -> None:
    context = build_context(response_text="structured answer")
    agent = FakeAgent()
    request = build_run_request_from_context(context, agent_name=agent.name)

    result = await agent.run(request=request, context=context)
    health = await agent.health()

    assert result.status == "completed"
    assert result.answer == "structured answer"
    assert result.agent_name == "fake_agent"
    assert result.usage == AgentUsageSummary(
        llm_calls=1,
        memory_searches=0,
        memory_writes=0,
        tool_calls=0,
        input_chars=len("Explain the architecture slice"),
        output_chars=len("structured answer"),
    )
    assert health == AgentHealthResult(
        agent_name="fake_agent",
        agent_type="custom",
        status="ok",
        enabled=True,
        configured_llm_profile=None,
        prompt_profile=None,
        memory_required=True,
        tools_required=True,
        streaming_supported=True,
        metadata={},
    )
    assert agent.descriptor().capabilities == AgentCapabilities(
        answer=True,
        review=False,
        stream=True,
        memory_read=True,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=False,
        tool_execute=True,
        self_managed_memory=True,
        self_managed_tools=True,
    )