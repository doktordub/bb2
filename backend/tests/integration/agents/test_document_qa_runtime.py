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
                    "stream_llm_deltas": True,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": True,
                    "known_prompt_profiles": ["document_qa_v1"],
                    "max_output_chars": 12000,
                    "max_llm_calls": 1,
                    "max_prompt_context_bytes": 4000,
                },
                "plugins": {
                    "support_agent": {
                        "enabled": True,
                        "type": "document_qa",
                        "display_name": "Document Agent",
                        "description": "Answers with bounded retrieved context.",
                        "llm_profile": "agent_profile",
                        "prompt_profile": "document_qa_v1",
                        "capabilities": {
                            "answer": True,
                            "stream": True,
                            "memory_read": True,
                            "memory_write": False,
                            "tool_intents": False,
                            "tool_execute": False,
                            "self_managed_memory": False,
                            "self_managed_tools": False,
                        },
                        "context_policy": {
                            "require_context_for_grounded_claims": True,
                            "cite_context_labels": True,
                            "max_context_items": 2,
                            "max_context_bytes": 500,
                        },
                    }
                },
            }
        }
    )


def build_context() -> tuple[OrchestrationContext, FakeLLMGateway, FakeTraceStore]:
    trace_store = FakeTraceStore()
    llm = FakeLLMGateway(response_text="document runtime answer", default_profile="gateway_default")
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the backend architecture.",
            usecase="document_chat",
            trace_id="trace_document_runtime",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=trace_store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "retrieval_augmented", "llm_profile": "retrieval_profile"},
        observability=build_fake_trace_recorder(store=trace_store),
    )
    return context, llm, trace_store


@pytest.mark.asyncio
async def test_registry_builds_and_runs_builtin_document_qa_agent() -> None:
    config = build_config()
    registry = DefaultAgentRegistry.from_config(config)
    agent = registry.resolve("support_agent")
    context, llm, trace_store = build_context()

    request = build_run_request_from_context(
        context,
        agent_name="support_agent",
        context_items=(
            PromptSection(
                title="Retrieved context",
                body="The architecture routes strategies through the orchestration runtime.",
                metadata={"source_label": "Architecture Doc"},
            ),
        ),
    )
    result = await agent.run(request=request, context=context)

    assert result.answer == "document runtime answer"
    assert result.output_items[0].source_label == "Architecture Doc"
    assert llm.requests[0].profile == "retrieval_profile"
    assert "agent_completed" in [event.resolved_event_name for event in trace_store.events]