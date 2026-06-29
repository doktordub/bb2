from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.plugins.document_qa import DocumentQaAgent
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


def build_context(*, response_text: str = "grounded answer") -> tuple[OrchestrationContext, FakeLLMGateway, FakeMemoryGateway, FakeToolGateway]:
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    memory = FakeMemoryGateway()
    tools = FakeToolGateway()
    trace_store = FakeTraceStore()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="What changed in the architecture?",
            usecase="document_chat",
            trace_id="trace_document_qa",
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=tools,
        trace=trace_store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "retrieval_augmented", "llm_profile": "retrieval_profile"},
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, memory, tools


@pytest.mark.asyncio
async def test_document_qa_uses_bounded_context_and_exposes_safe_source_labels() -> None:
    context, llm, memory, tools = build_context()
    agent = DocumentQaAgent(name="document_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)
    agent.context_policy = SimpleNamespace(
        require_context_for_grounded_claims=True,
        cite_context_labels=True,
        max_context_items=1,
        max_context_bytes=120,
    )

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        context_items=(
            PromptSection(
                title="Retrieved context",
                body="Architecture doc excerpt.",
                metadata={"source_label": "Architecture Doc"},
            ),
            PromptSection(
                title="Retrieved context",
                body="Second source that should be dropped by context limits.",
                metadata={"source_label": "Other Doc"},
            ),
        ),
    )

    result = await agent.run(request=request, context=context)

    assert result.answer == "grounded answer"
    assert result.llm_profile == "retrieval_profile"
    assert len(result.output_items) == 1
    assert result.output_items[0].source_label == "Architecture Doc"
    assert result.metadata["context_item_count"] == 1
    assert result.metadata["context_labels_included"] is True
    assert memory.search_requests == []
    assert tools.calls == []
    assert llm.requests[0].profile == "retrieval_profile"
    assert "untrusted quoted data" in str(llm.requests[0].messages[0].content).lower()


@pytest.mark.asyncio
async def test_document_qa_returns_safe_warning_when_context_is_required_but_missing() -> None:
    context, llm, _, _ = build_context(response_text="should not be used")
    agent = DocumentQaAgent(name="document_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)
    agent.context_policy = SimpleNamespace(
        require_context_for_grounded_claims=True,
        cite_context_labels=True,
        max_context_items=4,
        max_context_bytes=800,
    )

    request = build_run_request_from_context(context, agent_name=agent.name)

    result = await agent.run(request=request, context=context)

    assert result.answer == "I do not have retrieved context for a grounded answer yet."
    assert result.usage is not None
    assert result.usage.llm_calls == 0
    assert result.warnings[0].code == "grounded_context_missing"
    assert llm.requests == []