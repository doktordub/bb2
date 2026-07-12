from __future__ import annotations

import json

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


def build_task_first_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "task_chat"},
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
                        "allowed_usecases": ["task_chat"],
                        "planner_llm_profile": "planner_profile",
                        "executor_llm_profile": "executor_profile",
                        "memory_enabled": True,
                        "tools_enabled": False,
                        "max_steps": 8,
                        "max_tool_calls": 2,
                        "max_memory_searches": 2,
                        "max_llm_calls": 4,
                        "max_context_bytes": 2000,
                        "max_plan_steps": 4,
                        "max_execute_steps": 4,
                        "max_tool_loop_iterations": 2,
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["task_chat"],
                    },
                },
                "usecases": {
                    "task_chat": {
                        "enabled": True,
                        "strategy": "bounded_planner",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent", "task_execution_agent"],
                        "allowed_strategies": ["bounded_planner"],
                        "llm_profile": "executor_profile",
                        "policy_profile": "default",
                        "metadata": {"routing_mode": "task_first", "assessment_agent": "task_execution_agent"},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "type": "custom",
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                },
                "task_execution_agent": {
                    "enabled": True,
                    "type": "custom",
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                },
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


def build_task_execution_agent_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "task_execution_chat"},
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
                        "allowed_usecases": ["task_execution_chat"],
                        "planner_llm_profile": "executor_profile",
                        "executor_llm_profile": "executor_profile",
                        "memory_enabled": False,
                        "tools_enabled": False,
                        "max_steps": 8,
                        "max_tool_calls": 2,
                        "max_memory_searches": 2,
                        "max_llm_calls": 4,
                        "max_context_bytes": 2000,
                        "max_plan_steps": 4,
                        "max_execute_steps": 4,
                        "max_tool_loop_iterations": 2,
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["task_execution_chat"],
                    },
                },
                "usecases": {
                    "task_execution_chat": {
                        "enabled": True,
                        "strategy": "bounded_planner",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent", "task_execution_agent"],
                        "allowed_strategies": ["bounded_planner"],
                        "llm_profile": "executor_profile",
                        "policy_profile": "default",
                        "metadata": {
                            "routing_mode": "task_first",
                            "assessment_agent": "task_execution_agent",
                            "keep_visualization_override_disabled": True,
                        },
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "type": "custom",
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                },
                "task_execution_agent": {
                    "enabled": True,
                    "type": "task_execution",
                    "display_name": "Task Execution Agent",
                    "description": "Assess requests before bounded execution.",
                    "llm_profile": "executor_profile",
                    "prompt_profile": "task_execution_v1",
                },
            },
            "llm": {"defaults": {"profile": "executor_profile"}},
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


@pytest.mark.asyncio
async def test_bounded_planner_runtime_returns_task_first_direct_answer_without_plan() -> None:
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_task_first_config(),
        llm_gateway=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_task_first_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_task_first_runtime",
        user_id="user_1",
        message="My app is running slowly. Give me three first troubleshooting steps.",
        usecase="task_chat",
        metadata={
            "task_assessment": {
                "request_kind": "support_question",
                "response_mode": "direct_answer",
                "direct_answer_eligible": True,
                "direct_answer": "Check system utilization, inspect recent logs, and compare the slowdown to any recent deployment or configuration change.",
                "missing_required_inputs": [],
                "required_deterministic_computations": [],
                "suggested_task_list": [],
                "preferred_agents": ["support_agent"],
                "preferred_tools": [],
                "visualization_intent": False,
            }
        },
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_task_first_runtime",
        trace_id="trace_task_first_runtime",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer.startswith("Check system utilization")
    assert result.metadata["response_mode"] == "direct_answer"
    assert result.metadata["finish_reason"] == "direct_answer"
    assert result.state_delta is not None
    assert [step.step_type for step in result.steps] == ["strategy", "assessment"]


@pytest.mark.asyncio
async def test_bounded_planner_runtime_runs_real_task_execution_agent_for_direct_answer() -> None:
    llm = FakeLLMGateway(
        response_text=json.dumps(
            {
                "request_kind": "support_question",
                "response_mode": "direct_answer",
                "direct_answer_eligible": True,
                "direct_answer": "Check system utilization, inspect recent logs, and compare the slowdown to any recent deployment or configuration change.",
                "missing_required_inputs": [],
                "required_deterministic_computations": [],
                "suggested_task_list": [],
                "preferred_agents": ["support_agent"],
                "preferred_tools": [],
                "visualization_intent": False,
            }
        )
    )
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_task_execution_agent_config(),
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_task_execution_agent_direct"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_task_execution_agent_direct",
        user_id="user_1",
        message="My app is running slowly. Give me three first troubleshooting steps.",
        usecase="task_execution_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_task_execution_agent_direct",
        trace_id="trace_task_execution_agent_direct",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer.startswith("Check system utilization")
    assert result.metadata["request_kind"] == "support_question"
    assert result.metadata["response_mode"] == "direct_answer"
    assert result.metadata["finish_reason"] == "direct_answer"
    assert [step.step_type for step in result.steps] == ["strategy", "assessment"]
    assert len(llm.requests) == 1
    assert llm.requests[0].component == "agent.task_execution_agent"
    assert getattr(llm.requests[0].response_format, "type", None) == "json_object"


@pytest.mark.asyncio
async def test_bounded_planner_runtime_runs_real_task_execution_agent_for_clarification() -> None:
    llm = FakeLLMGateway(
        response_text=json.dumps(
            {
                "request_kind": "report_request",
                "response_mode": "request_user_input",
                "direct_answer_eligible": False,
                "clarification_question": "Which date range should I use?",
                "missing_required_inputs": ["date_range"],
                "required_deterministic_computations": [],
                "suggested_task_list": [],
                "preferred_agents": [],
                "preferred_tools": [],
                "visualization_intent": False,
            }
        )
    )
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_task_execution_agent_config(),
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_task_execution_agent_clarification"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_task_execution_agent_clarification",
        user_id="user_1",
        message="Build the monthly report.",
        usecase="task_execution_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_task_execution_agent_clarification",
        trace_id="trace_task_execution_agent_clarification",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "Which date range should I use?"
    assert result.metadata["request_kind"] == "report_request"
    assert result.metadata["response_mode"] == "request_user_input"
    assert result.metadata["needs_user_input"] is True
    assert result.metadata["finish_reason"] == "needs_user_input"
    assert [step.step_type for step in result.steps] == ["strategy", "assessment"]
    assert len(llm.requests) == 1
    assert llm.requests[0].component == "agent.task_execution_agent"