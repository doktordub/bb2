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
            "app": {"active_usecase": "project_plan"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "bounded_planner",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 2,
                    "max_memory_searches": 2,
                    "max_memory_writes": 1,
                    "max_llm_calls": 4,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                    "max_tool_loop_iterations": 2,
                    "max_context_bytes": 4000,
                },
                "strategies": {
                    "bounded_planner": {
                        "enabled": True,
                        "type": "bounded_planner",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_plan"],
                        "planner_llm_profile": "planner_profile",
                        "executor_llm_profile": "executor_profile",
                        "memory_enabled": True,
                        "tools_enabled": True,
                        "max_steps": 8,
                        "max_tool_calls": 2,
                        "max_memory_searches": 2,
                        "max_llm_calls": 4,
                        "max_context_bytes": 2000,
                        "max_plan_steps": 4,
                        "max_execute_steps": 4,
                        "max_tool_loop_iterations": 2,
                        "tools": {"allowed_tools": ["documents.search"], "max_calls": 2},
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_plan"],
                    },
                },
                "usecases": {
                    "project_plan": {
                        "enabled": True,
                        "strategy": "bounded_planner",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["bounded_planner", "direct_agent"],
                        "llm_profile": "executor_profile",
                        "policy_profile": "default",
                        "memory": {"enabled": True, "include_document_chunks": True, "default_limit": 2},
                        "tools": {"enabled": True, "allowed_tools": ["documents.search"]},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["documents.search"],
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
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
async def test_bounded_planner_runtime_executes_metadata_plan_and_persists_safe_summary() -> None:
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_config(),
        llm_gateway=FakeLLMGateway(response_text="executor answer"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_bounded_planner_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_bounded_planner_runtime",
        user_id="user_1",
        message="Find the architecture notes and summarize them.",
        usecase="project_plan",
        metadata={
            "planner_plan": {
                "plan_id": "plan_runtime",
                "steps": [
                    {
                        "step_id": "memory_1",
                        "action_type": "memory_search",
                        "name": "project_memory",
                        "inputs": {"query": "architecture notes", "limit": 2},
                    },
                    {
                        "step_id": "llm_1",
                        "action_type": "llm_call",
                        "name": "executor",
                        "inputs": {"prompt": "Summarize the current execution findings for the user."},
                    },
                    {
                        "step_id": "final_1",
                        "action_type": "finalize",
                        "name": "return_answer",
                        "inputs": {},
                    },
                ],
            }
        },
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_bounded_planner_runtime",
        trace_id="trace_bounded_planner_runtime",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "executor answer"
    assert result.strategy_name == "bounded_planner"
    assert result.metadata["planner_source"] == "request_metadata"
    assert result.metadata["plan_step_count"] == 3
    assert result.memory_searches[0].result_count == 0
    assert result.state_delta is not None
    assert result.state_delta.metadata_patch["plan_step_count"] == 3
    assert [step.step_type for step in result.steps] == ["strategy", "plan", "memory_search", "llm_call", "finalize"]