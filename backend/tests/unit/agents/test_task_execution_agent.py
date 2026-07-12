from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agents.plugins.task_execution_agent import TaskExecutionAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.testing.fakes import FakeConfigurationView, FakeLLMGateway, FakeMemoryGateway, FakePolicyService, FakeToolGateway, FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def build_context(response_text: str) -> tuple[OrchestrationContext, FakeLLMGateway]:
    llm = FakeLLMGateway(response_text=response_text)
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="My app is running slowly. Give me three first troubleshooting steps.",
            usecase="task_execution_chat",
            trace_id="trace_task_execution_agent",
            metadata={},
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView({"llm": {"defaults": {"profile": "local_reasoning"}}}),
        runtime_metadata={"strategy_name": "bounded_planner", "llm_profile": "local_reasoning"},
        observability=build_fake_trace_recorder(),
    )
    return context, llm


@pytest.mark.asyncio
async def test_task_execution_agent_normalizes_direct_answer_assessment_json() -> None:
    context, llm = build_context(
        json.dumps(
            {
                "request_kind": "support_question",
                "response_mode": "direct_answer",
                "direct_answer_eligible": True,
                "direct_answer": "Start by checking CPU, memory, and disk utilization; then inspect recent error logs; then compare latency against any recent deployment or configuration change.",
                "missing_required_inputs": [],
                "required_deterministic_computations": [],
                "suggested_task_list": [],
                "preferred_agents": ["support_agent"],
                "preferred_tools": [],
                "visualization_intent": False,
            }
        )
    )
    agent = TaskExecutionAgent(name="task_execution_agent")
    agent.default_llm_profile = "agent_profile"
    agent.prompt_profile = "task_execution_v1"
    agent.limits = SimpleNamespace(max_output_chars=2000, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer is not None
    payload = json.loads(result.answer)
    assert payload["response_mode"] == "direct_answer"
    assert payload["direct_answer"].startswith("Start by checking CPU")
    assert result.metadata["task_assessment"]["request_kind"] == "support_question"
    assert result.metadata["response_mode"] == "direct_answer"
    assert llm.requests[0].response_format is not None
    assert llm.requests[0].response_format.type == "json_object"


@pytest.mark.asyncio
async def test_task_execution_agent_normalizes_assessment_json_embedded_in_prose() -> None:
    context, _ = build_context(
            """
            I will use planned execution for this request.

            ```json
            {
                "request_kind": "visualization_request",
                "response_mode": "planned_execution",
                "direct_answer_eligible": false,
                "missing_required_inputs": [],
                "required_deterministic_computations": ["compound_growth_projection"],
                "suggested_task_list": [
                    {
                        "step_id": "chart_1",
                        "action_type": "agent_invoke",
                        "name": "chart_agent",
                        "inputs": {}
                    }
                ],
                "preferred_agents": ["chart_agent"],
                "preferred_tools": [],
                "visualization_intent": true
            }
            ```
            """
    )
    agent = TaskExecutionAgent(name="task_execution_agent")
    agent.default_llm_profile = "agent_profile"
    agent.prompt_profile = "task_execution_v1"
    agent.limits = SimpleNamespace(max_output_chars=2000, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer is not None
    payload = json.loads(result.answer)
    assert payload["response_mode"] == "planned_execution"
    assert payload["request_kind"] == "visualization_request"
    assert payload["visualization_intent"] is True
    assert payload["suggested_task_list"][0]["name"] == "chart_agent"


@pytest.mark.asyncio
async def test_task_execution_agent_canonicalizes_visualization_steps_to_chart_agent() -> None:
    context, _ = build_context(
        json.dumps(
            {
                "request_kind": "visualize_investment_growth",
                "response_mode": "planned_execution",
                "direct_answer_eligible": False,
                "direct_answer": None,
                "clarification_question": None,
                "missing_required_inputs": None,
                "required_deterministic_computations": [
                    "calculate_compound_interest",
                    "generate_line_chart",
                ],
                "suggested_task_list": [
                    {
                        "step_id": 1,
                        "action_type": "calculate",
                        "name": "Calculate compound interest for investment growth",
                        "inputs": {
                            "initial_investment": 10000,
                            "annual_growth_rate": 0.04,
                            "time_period_years": 10,
                        },
                    },
                    {
                        "step_id": 2,
                        "action_type": "generate",
                        "name": "Generate line chart for investment growth",
                        "inputs": {
                            "chart_title": "FTEC Investment Growth Over 10 Years",
                        },
                    },
                ],
                "preferred_agents": ["local_calculator", "chart_generator"],
                "preferred_tools": None,
                "visualization_intent": "line_chart",
            }
        )
    )
    agent = TaskExecutionAgent(name="task_execution_agent")
    agent.default_llm_profile = "agent_profile"
    agent.prompt_profile = "task_execution_v1"
    agent.limits = SimpleNamespace(max_output_chars=2000, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer is not None
    payload = json.loads(result.answer)
    assert payload["response_mode"] == "planned_execution"
    assert payload["visualization_intent"] is True
    assert payload["preferred_agents"] == ["chart_agent"]
    assert payload["suggested_task_list"] == [
        {
            "step_id": "chart_1",
            "action_type": "agent_invoke",
            "name": "chart_agent",
        }
    ]
