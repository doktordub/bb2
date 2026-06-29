from __future__ import annotations

import pytest

from app.contracts.memory import MemoryResult
from app.contracts.state import default_workflow_state
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.state_delta import workflow_state_snapshot_from_document
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "document_chat"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "retrieval_augmented",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_chat"],
                        "llm_profile": "retrieval_profile",
                        "memory_enabled": True,
                        "memory": {
                            "default_limit": 2,
                            "include_document_chunks": True,
                            "include_user_memory": True,
                        },
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_chat"],
                    },
                },
                "usecases": {
                    "document_chat": {
                        "enabled": True,
                        "strategy": "retrieval_augmented",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "retrieval_profile",
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 2,
                        },
                        "tools": {"enabled": False, "allowed_tools": []},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
            "memory": {"enabled": True},
            "observability": {
                "trace_enabled": True,
                "trace_payloads_enabled": True,
                "trace_store_required": True,
                "redact_secrets": True,
                "max_trace_payload_chars": 8000,
            },
        }
    )


@pytest.mark.asyncio
async def test_retrieval_runtime_returns_memory_search_summaries() -> None:
    config = build_config()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="retrieved runtime answer"),
        memory=FakeMemoryGateway(
            results=[
                MemoryResult(
                    memory_id="memory_1",
                    text="The orchestration runtime routes through configured strategies.",
                    memory_type="document_chunk",
                    source_id="architecture.md",
                )
            ]
        ),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_retrieval_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_retrieval_runtime",
        user_id="user_1",
        message="Summarize the architecture",
        usecase="document_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_retrieval_runtime",
        trace_id="trace_retrieval_runtime",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "retrieved runtime answer"
    assert result.strategy_name == "retrieval_augmented"
    assert [step.step_type for step in result.steps] == ["strategy", "memory_search", "agent"]
    assert result.memory_searches[0].result_count == 1
    assert result.state_delta is not None