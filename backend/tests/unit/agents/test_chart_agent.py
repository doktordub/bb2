from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from datetime import date

import pytest

from app.agents.factory import AgentFactory
from app.agents.plugins.chart_agent import ChartAgent
from app.agents.result_builder import build_run_request_from_context
from app.config.view import get_agents_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMToolCall
from app.contracts.tools import ToolDefinition, ToolExecutionResult
from app.orchestration.state_delta import WorkflowStateSnapshot
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeVisualizationGateway,
)
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder
from app.visualization.models import ChartDataSlice


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"
REPO_ROOT = Path(__file__).resolve().parents[4]
SUMMARY_FIXTURE = json.loads(
    (FIXTURE_DIR / "chart_context_summary_v1.json").read_text(encoding="utf-8")
)
DATASET_FIXTURE = json.loads(
    (
        REPO_ROOT
        / "mcp"
        / "tests"
        / "fixtures"
        / "visualization"
        / "structured_dataset_response_v1.json"
    ).read_text(encoding="utf-8")
)


def build_context(
    *,
    message: str,
    response_text: str,
    tool_calls: tuple[LLMToolCall | dict[str, object], ...] = (),
    visualization_gateway: FakeVisualizationGateway | None = None,
    tools: FakeToolGateway | None = None,
    memory: FakeMemoryGateway | None = None,
    state: WorkflowStateSnapshot | None = None,
    config: FakeConfigurationView | None = None,
) -> tuple[OrchestrationContext, FakeLLMGateway, FakeToolGateway, FakeMemoryGateway, FakeVisualizationGateway]:
    llm = FakeLLMGateway(
        response_text=response_text,
        default_profile="gateway_default",
        tool_calls=tool_calls,
    )
    resolved_tools = tools or FakeToolGateway()
    resolved_memory = memory or FakeMemoryGateway()
    resolved_visualization = visualization_gateway or FakeVisualizationGateway()
    trace_store = FakeTraceStore()
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_vis_001",
            message=message,
            usecase="default_chat",
            trace_id="trace_chart_agent",
        ),
        llm=llm,
        memory=resolved_memory,
        state=state,
        tools=resolved_tools,
        trace=trace_store,
        policy=FakePolicyService(),
        config=config or FakeConfigurationView(),
        runtime_metadata={"strategy_name": "direct_agent", "llm_profile": "local_reasoning"},
        observability=build_fake_trace_recorder(store=trace_store),
        metadata={"visualization_gateway": resolved_visualization},
    )
    return context, llm, resolved_tools, resolved_memory, resolved_visualization


def build_agent() -> ChartAgent:
    agent = ChartAgent(name="chart_agent")
    agent.default_llm_profile = "local_reasoning"
    agent.limits = SimpleNamespace(max_output_chars=1200, max_llm_calls=1)
    agent.allowed_tool_intents = ("reporting.query_metric_series",)
    return agent


def _ftec_price_markdown_message() -> str:
    return (
        "Draw a line chart for the below price data:\n\n"
        "# Daily Prices FTEC Stock\n"
        "| Date | Price |\n"
        "|------|------|\n"
        "| 6/17/2026 | $279.21 |\n"
        "| 6/16/2026 | $281.39 |\n"
        "| 6/15/2026 | $288.36 |\n"
        "| 6/14/2026 | $283.22 |\n"
        "| 6/13/2026 | $279.42 |\n"
        "| 6/12/2026 | $278.27 |"
    )


def test_agent_factory_builds_builtin_chart_agent() -> None:
    config = FakeConfigurationView(
        {
            "agents": {
                "defaults": {
                    "enabled": True,
                    "stream_llm_deltas": True,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": False,
                    "allow_self_managed_tools": False,
                    "allow_self_managed_memory": False,
                    "allow_memory_write": False,
                },
                "plugins": {
                    "chart_agent": {
                        "enabled": True,
                        "type": "chart_agent",
                        "display_name": "Chart Agent",
                        "description": "Chart plugin.",
                        "llm_profile": "local_reasoning",
                        "capabilities": {
                            "answer": True,
                            "review": False,
                            "stream": True,
                            "memory_read": True,
                            "memory_write": False,
                            "memory_candidate_extract": False,
                            "tool_intents": False,
                            "tool_execute": True,
                            "self_managed_memory": False,
                            "self_managed_tools": False,
                        },
                    }
                },
            }
        }
    )
    settings = get_agents_settings(config)
    factory = AgentFactory(settings=settings)

    agent = factory.build(settings.plugins["chart_agent"])

    assert isinstance(agent, ChartAgent)
    assert agent.name == "chart_agent"
    assert agent.type == "chart_agent"
    assert agent.default_llm_profile == "local_reasoning"


@pytest.mark.asyncio
async def test_chart_agent_builds_chart_from_inline_json_rows() -> None:
    message = (
        "Generate a grouped bar chart for income vs expense over the last 3 months using this data:\n"
        "```json\n"
        "[\n"
        '  {"month": "Jan", "income": 5200, "expense": 4100},\n'
        '  {"month": "Feb", "income": 5400, "expense": 4300},\n'
        '  {"month": "Mar", "income": 5100, "expense": 4600}\n'
        "]\n"
        "```"
    )
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "grouped_bar",
            "title": "Income vs Expense - Last 3 Months",
            "description": "Monthly comparison.",
            "x_field": "month",
            "y_fields": ["income", "expense"],
            "requires_data": True,
            "data_source_hint": "user_provided",
            "missing_information": [],
            "answer": "Here is the grouped bar chart for the last 3 months.",
        }
    )
    context, llm, tools, memory, visualization = build_context(message=message, response_text=response_text)
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the grouped bar chart for the last 3 months."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert result.metadata["artifact_count"] == 1
    assert len(result.output_items) == 2
    assert visualization.build_calls[0]["request"]["chart_type"] == "grouped_bar"
    assert visualization.build_calls[0]["request"]["data_source"] == "user_provided"
    assert [row["month"] for row in visualization.build_calls[0]["data"]] == ["Jan", "Feb", "Mar"]
    assert tools.calls == []
    assert memory.search_requests == []
    assert llm.requests[0].response_format is not None
    assert getattr(llm.requests[0].response_format, "type", None) == "json_object"


@pytest.mark.asyncio
async def test_chart_agent_builds_chart_from_inline_markdown_table_currency_rows() -> None:
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "line",
            "title": "FTEC Daily Prices",
            "requires_data": True,
            "answer": "Here is the line chart for FTEC prices.",
        }
    )
    context, _, tools, memory, visualization = build_context(
        message=_ftec_price_markdown_message(),
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the line chart for FTEC prices."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert visualization.build_calls[0]["request"]["chart_type"] == "line"
    assert visualization.build_calls[0]["request"]["x_field"] == "Date"
    assert visualization.build_calls[0]["request"]["y_fields"] == ["Price"]
    assert visualization.build_calls[0]["data"][0]["Price"] == 279.21
    assert tools.calls == []
    assert memory.search_requests == []


@pytest.mark.asyncio
async def test_chart_agent_parse_recovery_preserves_prompt_title_for_table_requests() -> None:
    message = (
        'Generate a table titled "Monthly Status Table" using this data:\n'
        '```json\n'
        '[\n'
        '  {"month": "2026-01", "status": "green", "revenue": 1200},\n'
        '  {"month": "2026-02", "status": "green", "revenue": 1350},\n'
        '  {"month": "2026-03", "status": "yellow", "revenue": 1500}\n'
        ']\n'
        '```'
    )
    context, _, tools, memory, visualization = build_context(
        message=message,
        response_text="not valid json",
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the table chart."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert visualization.build_calls[0]["request"]["chart_type"] == "table"
    assert visualization.build_calls[0]["request"]["title"] == "Monthly Status Table"
    assert tools.calls == []
    assert memory.search_requests == []


@pytest.mark.asyncio
async def test_chart_agent_inferrs_prompt_title_when_model_omits_title() -> None:
    message = (
        'Generate a table titled "Monthly Status Table" using this data:\n'
        '```json\n'
        '[\n'
        '  {"month": "2026-01", "status": "green", "revenue": 1200},\n'
        '  {"month": "2026-02", "status": "green", "revenue": 1350},\n'
        '  {"month": "2026-03", "status": "yellow", "revenue": 1500}\n'
        ']\n'
        '```'
    )
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "table",
            "requires_data": True,
            "answer": "Here is the table chart.",
        }
    )
    context, _, tools, memory, visualization = build_context(
        message=message,
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the table chart."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert visualization.build_calls[0]["request"]["chart_type"] == "table"
    assert visualization.build_calls[0]["request"]["title"] == "Monthly Status Table"
    assert tools.calls == []
    assert memory.search_requests == []


@pytest.mark.asyncio
async def test_chart_agent_synthesizes_compound_growth_projection_rows_locally() -> None:
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "line",
            "title": "Projected FTEC Investment Value",
            "requires_data": True,
            "answer": "Here is the projected investment value chart.",
        }
    )
    context, _, tools, memory, visualization = build_context(
        message=(
            "Draw a line chart showing value of a $10,000 investment into FTEC today "
            "over the next 10 years at a 4% annual growth rate."
        ),
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the projected investment value chart."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "deterministic_synthesis"
    assert visualization.build_calls[0]["request"]["chart_type"] == "line"
    assert visualization.build_calls[0]["request"]["x_field"] == "date"
    assert visualization.build_calls[0]["request"]["y_fields"] == ["projected_value"]
    assert visualization.build_calls[0]["data"][0] == {
        "date": date.today().isoformat(),
        "projected_value": 10000.0,
    }
    assert visualization.build_calls[0]["data"][-1]["projected_value"] == pytest.approx(14802.44)
    assert tools.calls == []
    assert memory.search_requests == []
    event_names = [event.resolved_event_name for event in context.trace.events]
    assert "deterministic_data_synthesized" in event_names


@pytest.mark.asyncio
async def test_chart_agent_accepts_embedded_json_response_payload() -> None:
    response_text = (
        "I will generate the chart now.\n"
        "```json\n"
        "{\n"
        '  "intent": "generate_chart",\n'
        '  "chart_type": "line",\n'
        '  "title": "FTEC Daily Prices",\n'
        '  "requires_data": true,\n'
        '  "answer": "Here is the line chart for FTEC prices."\n'
        "}\n"
        "```"
    )
    context, _, tools, memory, visualization = build_context(
        message=_ftec_price_markdown_message(),
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the line chart for FTEC prices."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert visualization.build_calls[0]["request"]["chart_type"] == "line"
    assert tools.calls == []
    assert memory.search_requests == []


@pytest.mark.asyncio
async def test_chart_agent_recovers_from_non_json_output_when_inline_chart_request_is_explicit() -> None:
    context, _, tools, memory, visualization = build_context(
        message=_ftec_price_markdown_message(),
        response_text="Here is the chart you asked for.",
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the line chart."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert visualization.build_calls[0]["request"]["chart_type"] == "line"
    assert visualization.build_calls[0]["request"]["y_fields"] == ["Price"]
    assert tools.calls == []
    assert memory.search_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_chart_type"),
    [
        (
            "Generate a grouped bar chart titled \"Income vs Expense\" with month on the x-axis and income and expense as the two series using this data:\n\n"
            "[\n"
            '  {"month": "2026-01", "income": 5200, "expense": 4100},\n'
            '  {"month": "2026-02", "income": 5400, "expense": 4300},\n'
            '  {"month": "2026-03", "income": 5600, "expense": 4500}\n'
            "]",
            "grouped_bar",
        ),
        (
            "Generate a stacked bar chart titled \"Sales Mix by Quarter\" with quarter on the x-axis and direct and partner stacked in each bar using this data:\n\n"
            "[\n"
            '  {"quarter": "Q1", "direct": 210, "partner": 90},\n'
            '  {"quarter": "Q2", "direct": 230, "partner": 110},\n'
            '  {"quarter": "Q3", "direct": 260, "partner": 130}\n'
            "]",
            "stacked_bar",
        ),
        (
            "Generate a horizontal bar chart titled \"Tickets by Team\" with team as the category and tickets as the value using this data:\n\n"
            "[\n"
            '  {"team": "Alpha", "tickets": 82},\n'
            '  {"team": "Beta", "tickets": 76},\n'
            '  {"team": "Gamma", "tickets": 64}\n'
            "]",
            "horizontal_bar",
        ),
    ],
)
async def test_chart_agent_prefers_explicit_prompt_chart_type_over_generic_model_type(
    message: str,
    expected_chart_type: str,
) -> None:
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "bar",
            "requires_data": True,
            "answer": "Here is the bar chart.",
        }
    )
    context, _, _, _, visualization = build_context(
        message=message,
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.metadata["response_mode"] == "chart_generated"
    assert visualization.build_calls[0]["request"]["chart_type"] == expected_chart_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "message",
        "response_text",
        "expected_chart_type",
        "expected_x_field",
        "expected_y_fields",
        "expected_series_field",
        "expected_value_field",
        "expected_options",
    ),
    [
        (
            "Generate a scatter chart titled \"Study Hours vs Score\" with hours on the x-axis and score on the y-axis using this data:\n\n"
            "[\n"
            '  {"hours": 2, "score": 68},\n'
            '  {"hours": 4, "score": 79},\n'
            '  {"hours": 6, "score": 91}\n'
            "]",
            "not valid json",
            "scatter",
            "hours",
            ["score"],
            None,
            "score",
            {},
        ),
        (
            "Generate a bubble chart titled \"Pipeline Quality\" with confidence on the x-axis, velocity on the y-axis, and amount as bubble size using this data:\n\n"
            "[\n"
            '  {"confidence": 0.65, "velocity": 18, "amount": 120000},\n'
            '  {"confidence": 0.80, "velocity": 24, "amount": 180000},\n'
            '  {"confidence": 0.55, "velocity": 15, "amount": 90000}\n'
            "]",
            "not valid json",
            "bubble",
            "confidence",
            ["velocity"],
            None,
            "velocity",
            {"size_field": "amount"},
        ),
        (
            "Generate a histogram chart titled \"Resolution Time Distribution\" using hours as the distribution value from this data:\n\n"
            "[\n"
            '  {"hours": 1.5},\n'
            '  {"hours": 2.0},\n'
            '  {"hours": 3.25},\n'
            '  {"hours": 4.0}\n'
            "]",
            "not valid json",
            "histogram",
            "hours",
            [],
            None,
            "hours",
            {},
        ),
        (
            "Generate a heatmap chart titled \"Usage Heatmap\" with month on the x-axis, region on the y-axis, and value as the cell intensity using this data:\n\n"
            "[\n"
            '  {"month": "2026-01", "region": "us-east", "value": 82},\n'
            '  {"month": "2026-01", "region": "eu-west", "value": 74},\n'
            '  {"month": "2026-02", "region": "us-east", "value": 91},\n'
            '  {"month": "2026-02", "region": "eu-west", "value": 79}\n'
            "]",
            "not valid json",
            "heatmap",
            "month",
            ["value"],
            "region",
            "value",
            {},
        ),
    ],
)
async def test_chart_agent_parse_recovery_infers_chart_specific_fields(
    message: str,
    response_text: str,
    expected_chart_type: str,
    expected_x_field: str,
    expected_y_fields: list[str],
    expected_series_field: str | None,
    expected_value_field: str,
    expected_options: dict[str, object],
) -> None:
    context, _, _, _, visualization = build_context(
        message=message,
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.metadata["response_mode"] == "chart_generated"
    build_request = visualization.build_calls[0]["request"]
    assert build_request["chart_type"] == expected_chart_type
    assert build_request["x_field"] == expected_x_field
    assert build_request["y_fields"] == expected_y_fields
    assert build_request["series_field"] == expected_series_field
    assert build_request["value_field"] == expected_value_field
    assert build_request["options"] == expected_options


@pytest.mark.asyncio
async def test_chart_agent_uses_allowed_tool_dataset_when_no_inline_rows() -> None:
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "grouped_bar",
            "title": "Income vs Expense - Last 6 Months",
            "x_field": "reporting_period",
            "y_fields": ["income", "expense"],
            "requires_data": True,
            "data_source_hint": "tool",
            "tool_name": "reporting.query_metric_series",
            "tool_arguments": {
                "metric_names": ["income", "expense"],
                "dimension": "reporting_period",
                "granularity": "month",
                "limit": 6,
            },
            "answer": "Here is the chart from the approved reporting dataset.",
        }
    )
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="reporting.query_metric_series",
                description="Reporting dataset query",
                enabled=True,
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ],
        execution_results={
            "reporting.query_metric_series": ToolExecutionResult(
                tool_name="reporting.query_metric_series",
                status="completed",
                structured_content=DATASET_FIXTURE,
            )
        },
    )
    context, _, resolved_tools, memory, visualization = build_context(
        message="Generate an income versus expense chart for the last 6 months.",
        response_text=response_text,
        tools=tools,
    )
    agent = build_agent()

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("reporting.query_metric_series",),
    )
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the chart from the approved reporting dataset."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "tool"
    assert len(resolved_tools.calls) == 1
    assert resolved_tools.calls[0].tool_name == "reporting.query_metric_series"
    assert visualization.build_calls[0]["request"]["data_source"] == "tool"
    assert visualization.build_calls[0]["data"][0]["income"] == 125000.0
    assert len(memory.search_requests) == 1


@pytest.mark.asyncio
async def test_chart_agent_prefers_inline_rows_over_native_tool_call() -> None:
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="reporting.query_metric_series",
                description="Reporting dataset query",
                enabled=True,
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ]
    )
    config = FakeConfigurationView(
        {
            "llm": {
                "profiles": {
                    "local_reasoning": {
                        "supports_tool_calling": True,
                    }
                }
            },
            "tooling": {
                "registry": {
                    "tools": {
                        "reporting.query_metric_series": {
                            "description": "Query visualization-ready reporting datasets.",
                            "input_schema_override": {
                                "type": "object",
                                "properties": {
                                    "metric_names": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "dimension": {"type": "string"},
                                    "start_date": {"type": "string"},
                                    "end_date": {"type": "string"},
                                },
                                "required": ["metric_names", "dimension"],
                                "additionalProperties": False,
                            },
                        }
                    }
                }
            },
        }
    )
    context, llm, resolved_tools, memory, visualization = build_context(
        message=_ftec_price_markdown_message(),
        response_text="",
        tool_calls=(
            {
                "id": "call_reporting_query_metric_series_1",
                "function": {
                    "name": "reporting.query_metric_series",
                    "arguments": json.dumps(
                        {
                            "metric_names": ["price"],
                            "dimension": "date",
                            "start_date": "2026-06-12",
                            "end_date": "2026-06-17",
                        }
                    ),
                },
            },
        ),
        tools=tools,
        config=config,
    )
    agent = build_agent()

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("reporting.query_metric_series",),
    )
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the line chart."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "user_provided"
    assert result.metadata["tool_calling_mode"] == "native"
    assert resolved_tools.calls == []
    assert memory.search_requests == []
    assert visualization.build_calls[0]["request"]["chart_type"] == "line"
    assert visualization.build_calls[0]["request"]["y_fields"] == ["Price"]
    assert visualization.build_calls[0]["data"][0]["Price"] == 279.21
    assert getattr(llm.requests[0].tool_choice, "type", None) == "auto"


@pytest.mark.asyncio
async def test_chart_agent_handles_native_tool_call_with_configured_tool_definition() -> None:
    price_dataset = {
        "schema_version": "1.0",
        "dataset_id": "ftec_june_2026_prices",
        "columns": [
            {"name": "date", "data_type": "date", "nullable": False, "semantic_role": "time"},
            {"name": "open", "data_type": "number", "nullable": False, "semantic_role": "metric"},
            {"name": "close", "data_type": "number", "nullable": False, "semantic_role": "metric"},
        ],
        "rows": [
            {"date": "2026-06-15", "open": 288.36, "close": 286.44},
            {"date": "2026-06-16", "open": 281.39, "close": 287.42},
            {"date": "2026-06-17", "open": 279.21, "close": 284.38},
        ],
        "row_count": 3,
        "truncated": False,
        "source": "reporting",
        "query_summary": "FTEC June 2026 daily prices.",
        "warnings": [],
        "provenance": {},
    }
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="reporting.query_metric_series",
                description="Reporting dataset query",
                enabled=True,
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ],
        execution_results={
            "reporting.query_metric_series": ToolExecutionResult(
                tool_name="reporting.query_metric_series",
                status="completed",
                structured_content=price_dataset,
            )
        },
    )
    config = FakeConfigurationView(
        {
            "llm": {
                "profiles": {
                    "local_reasoning": {
                        "supports_tool_calling": True,
                    }
                }
            },
            "tooling": {
                "registry": {
                    "tools": {
                        "reporting.query_metric_series": {
                            "description": "Query visualization-ready reporting datasets.",
                            "input_schema_override": {
                                "type": "object",
                                "properties": {
                                    "metric_names": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "dimension": {"type": "string"},
                                    "start_date": {"type": "string"},
                                    "end_date": {"type": "string"},
                                },
                                "required": ["metric_names", "dimension"],
                                "additionalProperties": False,
                            },
                        }
                    }
                }
            },
        }
    )
    context, llm, resolved_tools, memory, visualization = build_context(
        message="Draw a line chart for the price data.",
        response_text="",
        tool_calls=(
            {
                "id": "call_reporting_query_metric_series_1",
                "function": {
                    "name": "reporting.query_metric_series",
                    "arguments": json.dumps(
                        {
                            "metric_names": ["open", "close"],
                            "dimension": "date",
                            "start_date": "2026-06-01",
                            "end_date": "2026-06-30",
                        }
                    ),
                },
            },
        ),
        tools=tools,
        config=config,
    )
    agent = build_agent()

    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        available_tools=("reporting.query_metric_series",),
    )
    result = await agent.run(request=request, context=context)

    assert result.answer == "Here is the line chart."
    assert result.metadata["response_mode"] == "chart_generated"
    assert result.metadata["data_source"] == "tool"
    assert result.metadata["tool_calling_mode"] == "native"
    assert len(resolved_tools.calls) == 1
    assert resolved_tools.calls[0].arguments == {
        "metric_names": ["open", "close"],
        "dimension": "date",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
    }
    assert memory.search_requests == []
    assert visualization.build_calls[0]["request"]["chart_type"] == "line"
    assert visualization.build_calls[0]["request"]["x_field"] == "date"
    assert visualization.build_calls[0]["request"]["y_fields"] == ["open", "close"]
    assert getattr(llm.requests[0].response_format, "type", None) == "json_object"
    assert getattr(llm.requests[0].tool_choice, "type", None) == "auto"
    assert [tool.function.name for tool in llm.requests[0].tools] == ["reporting.query_metric_series"]
    assert llm.requests[0].tools[0].function.parameters == {
        "type": "object",
        "properties": {
            "metric_names": {
                "type": "array",
                "items": {"type": "string"},
            },
            "dimension": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
        },
        "required": ["metric_names", "dimension"],
        "additionalProperties": False,
    }


@pytest.mark.asyncio
async def test_chart_agent_requests_missing_data_instead_of_inventing_values() -> None:
    response_text = json.dumps(
        {
            "intent": "missing_data",
            "missing_information": ["income and expense values for each month"],
            "answer": "I can generate that chart, but I need the income and expense values for each month first.",
        }
    )
    context, _, tools, memory, visualization = build_context(
        message="Create a bar chart of income vs expense over the last 6 months.",
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert "need the income and expense values" in result.answer
    assert result.metadata["response_mode"] == "missing_data"
    assert visualization.build_calls == []
    assert tools.calls == []
    assert memory.search_requests == []


@pytest.mark.asyncio
async def test_chart_agent_lists_supported_alternatives_for_unsupported_chart_type() -> None:
    response_text = json.dumps(
        {
            "intent": "generate_chart",
            "chart_type": "sankey",
            "title": "Revenue flow",
            "requires_data": True,
            "answer": "Render a sankey chart.",
        }
    )
    context, _, _, _, visualization = build_context(
        message="Create a sankey chart for this revenue flow.",
        response_text=response_text,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert "Supported chart types include" in result.answer
    assert result.metadata["response_mode"] == "unsupported_chart_type"
    assert visualization.build_calls == []


@pytest.mark.asyncio
async def test_chart_agent_answers_summary_followup_without_artifact_retrieval() -> None:
    response_text = json.dumps(
        {
            "intent": "chart_followup",
            "question_type": "trend",
            "requires_exact_data": False,
            "required_fields": ["expense"],
        }
    )
    state = WorkflowStateSnapshot(
        session_id="session_vis_001",
        version=2,
        metadata={"visualization_context": {"summaries": [SUMMARY_FIXTURE]}},
    )
    context, _, _, _, visualization = build_context(
        message="What is the trend for expense in this chart?",
        response_text=response_text,
        state=state,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert "Moderate upward trend with March and May spikes" in result.answer
    assert result.metadata["response_mode"] == "chart_followup_summary"
    assert visualization.retrieve_calls == []


@pytest.mark.asyncio
async def test_chart_agent_uses_deterministic_retrieval_for_exact_followup() -> None:
    response_text = json.dumps(
        {
            "intent": "chart_followup",
            "referenced_artifact_id": SUMMARY_FIXTURE["artifact_id"],
            "question_type": "value_lookup",
            "requires_exact_data": True,
            "required_fields": ["month", "expense"],
            "filters": {"month": "Mar"},
        }
    )
    visualization = FakeVisualizationGateway(
        retrieval_results={
            (SUMMARY_FIXTURE["artifact_id"], "data_slice"): ChartDataSlice(
                artifact_id=SUMMARY_FIXTURE["artifact_id"],
                chart_type=SUMMARY_FIXTURE["chart_type"],
                data_ref=SUMMARY_FIXTURE["data_ref"],
                fields=["month", "expense"],
                rows=[{"month": "Mar", "expense": 4600}],
                row_count=1,
                truncated=False,
            )
        }
    )
    state = WorkflowStateSnapshot(
        session_id="session_vis_001",
        version=2,
        metadata={"visualization_context": {"summaries": [SUMMARY_FIXTURE]}},
    )
    context, _, _, _, visualization = build_context(
        message="What was the expense in Mar for chart_income_expense_last_6_months?",
        response_text=response_text,
        visualization_gateway=visualization,
        state=state,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert "expense was 4600" in result.answer
    assert result.metadata["response_mode"] == "chart_followup_retrieval"
    assert len(visualization.retrieve_calls) == 1
    assert visualization.retrieve_calls[0]["artifact_id"] == SUMMARY_FIXTURE["artifact_id"]
    assert visualization.retrieve_calls[0]["return_type"] == "data_slice"


def test_chart_agent_prompt_sections_select_only_relevant_chart_summaries() -> None:
    unrelated_summary = {
        **SUMMARY_FIXTURE,
        "artifact_id": "chart_headcount_last_6_months",
        "title": "Headcount Trend",
        "x_field": "month",
        "y_fields": ["headcount"],
        "summary_text": "Headcount stays flat.",
        "key_insights": ["Headcount is stable."],
    }
    state = WorkflowStateSnapshot(
        session_id="session_vis_001",
        version=2,
        metadata={
            "visualization_context": {
                "summaries": [unrelated_summary, SUMMARY_FIXTURE],
            }
        },
    )
    config = FakeConfigurationView(
        {
            "visualization": {
                "enabled": True,
                "context_summary": {
                    "enabled": True,
                    "mode": "summary_only",
                    "max_chart_summaries_per_session_context": 1,
                    "max_total_visualization_context_tokens": 1800,
                },
            }
        }
    )
    context, _, _, _, _ = build_context(
        message="What is the trend for expense in this chart?",
        response_text=json.dumps({"intent": "not_chart", "answer": "unused"}),
        state=state,
        config=config,
    )
    agent = build_agent()

    request = build_run_request_from_context(context, agent_name=agent.name)
    sections = agent.build_extra_prompt_sections(request=request, context=context)

    summary_sections = [section for section in sections if section.title.startswith("Known chart summary")]
    assert len(summary_sections) == 1
    assert "chart_income_expense_last_6_months" in summary_sections[0].body
    assert "chart_headcount_last_6_months" not in summary_sections[0].body