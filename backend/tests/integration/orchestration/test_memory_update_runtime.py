from __future__ import annotations

import pytest

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
            "app": {"active_usecase": "memory_capture"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "memory_update",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 1,
                    "max_memory_searches": 1,
                    "max_memory_writes": 1,
                    "max_llm_calls": 1,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "memory_update": {
                        "enabled": True,
                        "type": "memory_update",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["memory_capture"],
                        "memory_enabled": True,
                        "memory_write_enabled": True,
                        "max_memory_writes": 1,
                        "candidate_limit": 2,
                        "require_policy_approval": True,
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["memory_capture"],
                    },
                },
                "usecases": {
                    "memory_capture": {
                        "enabled": True,
                        "strategy": "memory_update",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["memory_update", "direct_agent"],
                        "policy_profile": "default",
                        "memory": {"enabled": True},
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
            "policy": {"profiles": {"default": {"allow_memory_writes": True}}},
            "memory": {
                "enabled": True,
                "lifecycle": {"allow_writes": True},
            },
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
async def test_memory_update_runtime_returns_safe_memory_update_summaries() -> None:
    memory = FakeMemoryGateway()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_config(),
        llm_gateway=FakeLLMGateway(response_text="unused"),
        memory=memory,
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_memory_update_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_memory_update_runtime",
        user_id="user_1",
        message="Remember that the repo root is backend/.",
        usecase="memory_capture",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_memory_update_runtime",
        trace_id="trace_memory_update_runtime",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "I stored 1 memory update for future turns."
    assert result.strategy_name == "memory_update"
    assert result.memory_updates[0].status == "ok"
    assert result.memory_updates[0].metadata["memory_type"] == "user_fact"
    assert "affected_ids" not in result.memory_updates[0].metadata
    assert len(memory.writes) == 1
    assert result.state_delta is not None
    assert result.state_delta.metadata_patch["memory_update_count"] == 1
    assert result.state_delta.metadata_patch["last_memory_updates"][0]["status"] == "ok"
    assert result.state_delta.append_messages[0].metadata["memory_update_count"] == 1
    assert [step.step_type for step in result.steps] == [
        "strategy",
        "memory_candidate_extraction",
        "memory_write",
    ]