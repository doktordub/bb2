from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config.view import (
    SessionConcurrencySettings,
    SessionDefaultsSettings,
    SessionHistorySettings,
    SessionIdentifierSettings,
    SessionLifecycleSettings,
    SessionSettings,
    SessionStateSettings,
    SessionTracingSettings,
)
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMRequest, LLMResponse, LLMTokenUsage
from app.contracts.tools import ToolDefinition, ToolExecutionRequest, ToolExecutionResult, ToolScopes
from app.contracts.trace import TOOL_CALL_COMPLETED, TOOL_CALL_STARTED
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore
from app.policy.service import DefaultPolicyService
from app.session.mapping import build_session_chat_request, build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes import (
    FakeConfigurationView,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_llm import FakeLLMGateway
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder
from app.tools.factory import build_tooling_runtime, initialize_tooling_runtime
from app.tools.mcp import FakeMCPClientAdapter, MCPToolCallResult, MCPToolDefinition
from app.visualization.artifact_store import build_visualization_artifact_scope
from app.visualization.gateway import build_visualization_runtime


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
DATASET_FIXTURE = json.loads(
    (
        WORKSPACE_ROOT
        / "mcp"
        / "tests"
        / "fixtures"
        / "visualization"
        / "structured_dataset_response_v1.json"
    ).read_text(encoding="utf-8")
)
QUERY_ERROR_FIXTURE = json.loads(
    (
        WORKSPACE_ROOT
        / "mcp"
        / "tests"
        / "fixtures"
        / "visualization"
        / "query_metric_series_error_v1.json"
    ).read_text(encoding="utf-8")
)
CHART_VALIDATION_CASES = tuple(
    json.loads(
        (
            WORKSPACE_ROOT
            / "backend"
            / "tests"
            / "fixtures"
            / "visualization"
            / "chart_validation_cases_v1.json"
        ).read_text(encoding="utf-8")
    )["cases"]
)
TASK_EXECUTION_FTEC_MESSAGE = (
    "Draw a line chart showing value of a $10,000 investment into FTEC today "
    "over the next 10 years at a 4% annual growth rate."
)
_TASK_EXECUTION_VALUE_LOOKUP_RE = re.compile(
    r"projected value on (?P<date>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


class VisualizationFlowLLMGateway(FakeLLMGateway):
    def _resolve_response_text(self, request: LLMRequest) -> str:
        prompt_text = _prompt_text(request)
        if "What was the expense in 2026-03-01?" in prompt_text:
            return json.dumps(
                {
                    "intent": "chart_followup",
                    "referenced_artifact_id": "",
                    "question_type": "value_lookup",
                    "requires_exact_data": True,
                    "required_fields": ["reporting_period", "expense"],
                    "filters": {"reporting_period": "2026-03-01"},
                }
            )

        return json.dumps(
            {
                "intent": "generate_chart",
                "chart_type": "grouped_bar",
                "title": "Income vs Expense - Last 6 Months",
                "description": "Monthly income and expense comparison.",
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
                "answer": "Here is the income versus expense chart for the last 6 months.",
            }
        )

    async def complete(self, request: LLMRequest, context):  # type: ignore[override]
        self.requests.append(request)
        self.contexts.append(context)
        profile = request.profile or self.default_profile
        return LLMResponse(
            text=self._resolve_response_text(request),
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            finish_reason="completed",
            usage=LLMTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            metadata={"component": request.component} if request.component else {},
        )


class TaskExecutionVisualizationFlowLLMGateway(VisualizationFlowLLMGateway):
    def _resolve_response_text(self, request: LLMRequest) -> str:
        prompt_text = _prompt_text(request)
        component = request.component or ""
        date_match = _TASK_EXECUTION_VALUE_LOOKUP_RE.search(prompt_text)

        if component == "agent.task_execution_agent":
            if date_match is not None:
                return json.dumps(
                    {
                        "request_kind": "chart_followup",
                        "response_mode": "planned_execution",
                        "direct_answer_eligible": False,
                        "missing_required_inputs": [],
                        "required_deterministic_computations": [],
                        "suggested_task_list": [
                            {
                                "step_id": "chart_followup_1",
                                "action_type": "agent_invoke",
                                "name": "chart_agent",
                                "inputs": {},
                            },
                            {
                                "step_id": "finalize_1",
                                "action_type": "finalize",
                                "name": "return_answer",
                                "inputs": {},
                            },
                        ],
                        "preferred_agents": ["chart_agent"],
                        "preferred_tools": [],
                        "visualization_intent": True,
                    }
                )
            if TASK_EXECUTION_FTEC_MESSAGE in prompt_text:
                return json.dumps(
                    {
                        "request_kind": "visualization_request",
                        "response_mode": "planned_execution",
                        "direct_answer_eligible": False,
                        "missing_required_inputs": [],
                        "required_deterministic_computations": ["compound_growth_projection"],
                        "suggested_task_list": [
                            {
                                "step_id": "chart_1",
                                "action_type": "agent_invoke",
                                "name": "chart_agent",
                                "inputs": {},
                            },
                            {
                                "step_id": "finalize_1",
                                "action_type": "finalize",
                                "name": "return_answer",
                                "inputs": {},
                            },
                        ],
                        "preferred_agents": ["chart_agent"],
                        "preferred_tools": [],
                        "visualization_intent": True,
                    }
                )

        if component == "agent.chart_agent":
            if date_match is not None:
                return json.dumps(
                    {
                        "intent": "chart_followup",
                        "referenced_artifact_id": "",
                        "question_type": "value_lookup",
                        "requires_exact_data": True,
                        "required_fields": ["date", "projected_value"],
                        "filters": {"date": date_match.group("date")},
                    }
                )
            if TASK_EXECUTION_FTEC_MESSAGE in prompt_text:
                return json.dumps(
                    {
                        "intent": "generate_chart",
                        "chart_type": "line",
                        "title": "Projected FTEC Investment Value",
                        "requires_data": True,
                        "answer": "Here is the projected investment value chart.",
                    }
                )

        return super()._resolve_response_text(request)


class FixtureDrivenTaskExecutionVisualizationLLMGateway(TaskExecutionVisualizationFlowLLMGateway):
    def __init__(self, *, case: dict[str, object], default_profile: str = "local_reasoning") -> None:
        super().__init__(default_profile=default_profile)
        self._case = case

    def _resolve_response_text(self, request: LLMRequest) -> str:
        component = request.component or ""

        if component == "agent.task_execution_agent":
            return json.dumps(
                {
                    "request_kind": "visualization_request",
                    "response_mode": "planned_execution",
                    "direct_answer_eligible": False,
                    "missing_required_inputs": [],
                    "required_deterministic_computations": [],
                    "suggested_task_list": [
                        {
                            "step_id": "chart_1",
                            "action_type": "agent_invoke",
                            "name": "chart_agent",
                            "inputs": {},
                        },
                        {
                            "step_id": "finalize_1",
                            "action_type": "finalize",
                            "name": "return_answer",
                            "inputs": {},
                        },
                    ],
                    "preferred_agents": ["chart_agent"],
                    "preferred_tools": [],
                    "visualization_intent": True,
                }
            )

        if component == "agent.chart_agent":
            return json.dumps(_build_chart_intent_from_validation_case(self._case))

        return super()._resolve_response_text(request)


class WeakAssessmentFixtureDrivenTaskExecutionVisualizationLLMGateway(
    FixtureDrivenTaskExecutionVisualizationLLMGateway
):
    def _resolve_response_text(self, request: LLMRequest) -> str:
        component = request.component or ""
        if component == "agent.task_execution_agent":
            return json.dumps(
                {
                    "request_kind": "general_request",
                    "response_mode": "direct_answer",
                    "direct_answer_eligible": True,
                    "direct_answer": "Here is a markdown table summary.",
                    "missing_required_inputs": [],
                    "required_deterministic_computations": [],
                    "suggested_task_list": [],
                    "preferred_agents": ["support_agent"],
                    "preferred_tools": [],
                    "visualization_intent": False,
                }
            )
        return super()._resolve_response_text(request)


class BrokenAssessmentFixtureDrivenTaskExecutionVisualizationLLMGateway(
    FixtureDrivenTaskExecutionVisualizationLLMGateway
):
    def _resolve_response_text(self, request: LLMRequest) -> str:
        component = request.component or ""
        if component == "agent.task_execution_agent":
            return "Generate a markdown table with the provided rows."
        return super()._resolve_response_text(request)

def _prompt_text(request: LLMRequest) -> str:
    rendered: list[str] = []
    for message in request.messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            rendered.append(content)
            continue
        if isinstance(content, list):
            rendered.append(
                " ".join(
                    part.text or ""
                    for part in content
                    if hasattr(part, "text")
                )
            )
    return "\n".join(rendered)


def _build_session_settings(
    *,
    default_usecase: str = "default_chat",
    history_enabled: bool = False,
) -> SessionSettings:
    return SessionSettings(
        enabled=True,
        identifiers=SessionIdentifierSettings(
            prefix="session",
            accept_client_session_id=True,
            generate_when_missing=True,
            max_length=128,
            allowed_pattern="^[A-Za-z0-9_.:-]{3,128}$",
        ),
        defaults=SessionDefaultsSettings(
            default_user_id="local_user",
            default_usecase=default_usecase,
            default_history_limit=50,
            max_history_limit=200,
            timezone_metadata_key="timezone",
        ),
        lifecycle=SessionLifecycleSettings(
            create_on_first_chat=True,
            resume_existing_sessions=True,
            reject_unknown_client_session_id=False,
            update_last_seen_on_load=True,
            save_after_failed_orchestration=True,
            save_after_cancelled_stream=True,
        ),
        concurrency=SessionConcurrencySettings(
            mode="optimistic_version",
            conflict_policy="reject",
            max_retries=1,
        ),
        state=SessionStateSettings(
            save_on_chat_completion=True,
            save_on_stream_completion=True,
            save_on_stream_cancellation=True,
            save_on_stream_failure=True,
            save_each_stream_delta=False,
        ),
        history=SessionHistorySettings(
            enabled=history_enabled,
            include_tool_summaries=False,
            include_system_messages=False,
            include_metadata=True,
            max_message_chars=4000,
            redaction_enabled=True,
        ),
        tracing=SessionTracingSettings(
            record_session_created=True,
            record_session_resumed=True,
            record_session_reset=True,
            record_state_loaded=True,
            record_state_saved=True,
            record_history_returned=True,
            record_stream_lifecycle=True,
        ),
    )


def _build_context(
    *,
    trace_id: str,
    request_id: str,
    path: str = "/chat",
    method: str = "POST",
) -> object:
    return build_session_request_context(
        trace_id=trace_id,
        request_id=request_id,
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path=path,
        method=method,
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": trace_id},
    )


def _validation_case_artifact(case: dict[str, object]) -> dict[str, object]:
    artifact = case.get("artifact")
    if not isinstance(artifact, dict):
        raise AssertionError("Validation case is missing an artifact payload.")
    return artifact


def _validation_case_encoding(case: dict[str, object]) -> dict[str, object]:
    encoding = _validation_case_artifact(case).get("encoding")
    if not isinstance(encoding, dict):
        raise AssertionError("Validation case is missing an encoding payload.")
    return encoding


def _build_chart_intent_from_validation_case(case: dict[str, object]) -> dict[str, object]:
    artifact = _validation_case_artifact(case)
    encoding = _validation_case_encoding(case)
    chart_type = str(case["chart_type"])
    payload: dict[str, object] = {
        "intent": "generate_chart",
        "chart_type": chart_type,
        "title": artifact["title"],
        "description": artifact.get("description"),
        "requires_data": True,
        "data_source_hint": "user_provided",
        "answer": f"Here is the {chart_type.replace('_', ' ')} chart.",
    }

    if chart_type in {"bar", "horizontal_bar", "line", "area", "radar", "box_plot"}:
        payload["x_field"] = encoding["x"]
        payload["y_fields"] = list(encoding["y"])
        if "time" in encoding:
            payload["time_field"] = encoding["time"]
        return payload

    if chart_type in {"grouped_bar", "stacked_bar", "multi_line"}:
        payload["x_field"] = encoding["x"]
        payload["y_fields"] = list(encoding["y"])
        if "time" in encoding:
            payload["time_field"] = encoding["time"]
        return payload

    if chart_type in {"pie", "donut", "treemap"}:
        payload["category_field"] = encoding["category"]
        payload["value_field"] = encoding["value"]
        return payload

    if chart_type == "waterfall":
        payload["x_field"] = encoding["x"]
        payload["value_field"] = encoding["value"]
        return payload

    if chart_type == "scatter":
        payload["x_field"] = encoding["x"]
        payload["y_fields"] = [encoding["y"]]
        return payload

    if chart_type == "bubble":
        payload["x_field"] = encoding["x"]
        payload["y_fields"] = [encoding["y"]]
        payload["size_field"] = encoding["size"]
        return payload

    if chart_type == "histogram":
        payload["x_field"] = encoding["x"]
        return payload

    if chart_type == "heatmap":
        payload["x_field"] = encoding["x"]
        payload["series_field"] = encoding["y"]
        payload["value_field"] = encoding["value"]
        return payload

    if chart_type == "gantt":
        payload["x_field"] = encoding["task"]
        payload["start_field"] = encoding["start"]
        payload["end_field"] = encoding["end"]
        return payload

    if chart_type == "table":
        return payload

    raise AssertionError(f"Unsupported validation case chart type: {chart_type}")


def _build_prompt_from_validation_case(case: dict[str, object]) -> str:
    artifact = _validation_case_artifact(case)
    data = artifact.get("data")
    if not isinstance(data, list):
        raise AssertionError("Validation case prompt generation requires inline data.")
    chart_type = str(case["chart_type"]).replace("_", " ")
    title = str(artifact["title"])
    if chart_type == "table":
        return (
            f'Generate a table titled "{title}" using this data:\n\n'
            f"```json\n{json.dumps(data, indent=2)}\n```"
        )
    return (
        f'Generate a {chart_type} chart titled "{title}" using this data:\n\n'
        f"```json\n{json.dumps(data, indent=2)}\n```"
    )


def _build_percentage_split_case() -> dict[str, object]:
    return {
        "chart_type": "pie",
        "artifact": {
            "chart_type": "pie",
            "title": "Yes vs No",
            "description": "Share of yes versus no.",
            "renderer": "echarts",
            "spec_version": "1.0",
            "data_mode": "inline",
            "data": [
                {"label": "yes", "value": 77},
                {"label": "no", "value": 23},
            ],
            "encoding": {"category": "label", "value": "value"},
            "warnings": [],
        },
    }


def _build_chart_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
            "usecases": {"default_chat": {"enabled": True}},
            "visualization": {
                "enabled": True,
                "context_summary": {
                    "enabled": True,
                    "mode": "summary_only",
                    "max_tokens_per_chart_summary": 600,
                    "max_chart_summaries_per_session_context": 5,
                    "max_total_visualization_context_tokens": 1800,
                    "include_data_ref": True,
                    "include_aggregate_stats": True,
                    "include_extrema": True,
                    "include_trend_summary": True,
                    "include_sample_rows": False,
                    "max_sample_rows": 0,
                    "eviction_policy": "most_recent_relevant",
                },
                "artifact_store": {
                    "enabled": True,
                    "provider": "memory",
                    "ttl_seconds": 7200,
                    "allow_reference_data_mode": True,
                    "public_retrieval_enabled": True,
                    "exact_followup_retrieval_enabled": True,
                    "retrieval_endpoint": "/artifacts/{artifact_id}",
                },
            },
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                    "conversation_context": {
                        "enabled": False,
                        "mode": "window",
                        "max_messages": 12,
                        "max_chars": 12000,
                        "include_assistant_messages": True,
                        "summary_threshold_messages": 24,
                        "summary_max_chars": 2000,
                    },
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "chart_agent",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "local_reasoning",
                        "memory_enabled": True,
                        "tools_enabled": True,
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "chart_agent",
                        "allowed_agents": ["chart_agent"],
                        "allowed_strategies": ["direct_agent"],
                        "llm_profile": "local_reasoning",
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 2,
                        },
                        "tools": {
                            "enabled": True,
                            "allowed_tools": ["reporting.query_metric_series"],
                        },
                    }
                },
            },
            "agents": {
                "chart_agent": {
                    "enabled": True,
                    "type": "chart_agent",
                    "description": "Visualization verification agent.",
                    "llm_profile": "local_reasoning",
                    "allowed_tool_intents": ["reporting.query_metric_series"],
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
            "llm": {"defaults": {"profile": "local_reasoning"}},
            "memory": {"enabled": True},
            "observability": {
                "trace_enabled": True,
                "trace_payloads_enabled": False,
                "trace_store_required": True,
                "redact_secrets": True,
                "max_trace_payload_chars": 8000,
            },
        }
    )


def _build_real_tooling_config() -> FakeConfigurationView:
    config = _build_chart_config()
    config.values["llm"] = {
        "defaults": {"profile": "local_reasoning"},
        "providers": {
            "local_provider": {
                "type": "openai_compatible",
                "enabled": True,
                "base_url": "http://localhost:8081/v1",
                "api_key": "fake-key",
            }
        },
        "profiles": {
            "local_reasoning": {
                "enabled": True,
                "provider": "local_provider",
                "model": "local-reasoning-model",
                "temperature": 0.2,
                "supports_streaming": True,
                "supports_json_schema": True,
                "supports_tool_calling": False,
                "allowed_for": {
                    "usecases": ["default_chat"],
                    "agents": ["chart_agent"],
                    "strategies": ["direct_agent"],
                },
                "fallback_profiles": [],
            }
        },
    }
    config.values["tooling"] = {
        "enabled": True,
        "defaults": {
            "timeout_seconds": 30,
            "stream_timeout_seconds": 60,
            "max_retries": 0,
            "max_argument_bytes": 8192,
            "max_result_bytes": 131072,
            "trace_arguments": False,
            "trace_results": False,
            "discovery_on_startup": True,
            "discovery_refresh_seconds": 300,
        },
        "registry": {
            "allow_discovered_tools": True,
            "require_configured_allowlist": True,
            "tools": {
                "reporting.query_metric_series": {
                    "enabled": True,
                    "mcp_tool_name": "reporting.query_metric_series",
                    "description": "Reporting dataset query",
                    "allowed_for": {
                        "usecases": ["default_chat"],
                        "agents": ["chart_agent"],
                        "strategies": ["direct_agent"],
                    },
                    "timeout_seconds": 30,
                    "max_argument_bytes": 8192,
                    "max_result_bytes": 131072,
                    "approval_required": False,
                    "input_schema_override": {
                        "type": "object",
                        "properties": {
                            "metric_names": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "dimension": {"type": "string", "minLength": 1},
                            "start_date": {"type": "string"},
                            "end_date": {"type": "string"},
                            "filters": {"type": "object"},
                            "aggregation": {
                                "type": "string",
                                "enum": ["sum", "avg", "min", "max", "count"],
                            },
                            "granularity": {
                                "type": "string",
                                "enum": ["day", "week", "month", "quarter", "year", "category"],
                            },
                            "sort": {"type": "string", "enum": ["asc", "desc"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        },
                        "required": ["metric_names", "dimension"],
                        "additionalProperties": False,
                    },
                    "tags": ["reporting", "visualization"],
                    "safety_level": "read_only",
                }
            },
        },
    }
    config.values["mcp"] = {
        "main": {
            "name": "fake_reporting",
            "enabled": True,
            "endpoint": "http://tooling.invalid/mcp",
            "transport": "http",
            "timeout_seconds": 30,
            "stream_timeout_seconds": 60,
            "auth": {"mode": "none"},
            "tool_discovery_enabled": True,
        }
    }
    config.values["policy"] = {
        "default_profile": "default",
        "profiles": {
            "default": {
                "deny_unknown_tools": True,
                "deny_unknown_llm_profiles": True,
                "require_memory_scope": True,
                "allow_memory_writes": False,
                "usecases": {"allowed": ["default_chat"]},
                "strategies": {"allowed": ["direct_agent"]},
                "agents": {"allowed": ["chart_agent"]},
                "llm": {"allowed_profiles": ["local_reasoning"]},
                "memory": {"allowed_read_scopes": ["project", "usecase", "user"]},
                "tools": {
                    "allowed_tools": ["reporting.query_metric_series"],
                    "allow_write_tools": False,
                    "allow_destructive_tools": False,
                    "allow_external_side_effect_tools": False,
                    "allow_approval_required_tools": False,
                },
            }
        },
    }
    return config


def _build_task_execution_chart_config() -> FakeConfigurationView:
    config = _build_chart_config()
    config.values["app"] = {"active_usecase": "task_execution_chat"}
    config.values["usecases"] = {"task_execution_chat": {"enabled": True}}

    orchestration = config.values["orchestration"]
    orchestration["defaults"] = {
        **orchestration["defaults"],
        "strategy": "bounded_planner",
        "fallback_strategy": "fallback_answer",
        "max_memory_writes": 1,
        "max_tool_loop_iterations": 2,
        "max_context_bytes": 4000,
    }
    orchestration["strategies"] = {
        "bounded_planner": {
            "enabled": True,
            "type": "bounded_planner",
            "default_agent": "support_agent",
            "allowed_usecases": ["task_execution_chat"],
            "planner_llm_profile": "local_reasoning",
            "executor_llm_profile": "local_reasoning",
            "memory_enabled": True,
            "tools_enabled": True,
            "max_steps": 8,
            "max_tool_calls": 4,
            "max_memory_searches": 3,
            "max_memory_writes": 1,
            "max_llm_calls": 6,
            "max_context_bytes": 4000,
            "max_plan_steps": 4,
            "max_execute_steps": 4,
            "max_tool_loop_iterations": 2,
            "tools": {"allowed_tools": ["reporting.query_metric_series"]},
        },
        "fallback_answer": {
            "enabled": True,
            "type": "fallback_answer",
            "allowed_usecases": ["task_execution_chat"],
            "llm_profile": "local_reasoning",
        },
    }
    orchestration["usecases"] = {
        "task_execution_chat": {
            "enabled": True,
            "strategy": "bounded_planner",
            "agent": "support_agent",
            "allowed_agents": ["task_execution_agent", "support_agent", "chart_agent"],
            "allowed_strategies": ["bounded_planner", "fallback_answer"],
            "llm_profile": "local_reasoning",
            "policy_profile": "default",
            "memory": {
                "enabled": True,
                "include_document_chunks": True,
                "default_limit": 2,
            },
            "tools": {
                "enabled": True,
                "allowed_tools": ["reporting.query_metric_series"],
            },
            "metadata": {
                "routing_mode": "task_first",
                "assessment_agent": "task_execution_agent",
                "keep_visualization_override_disabled": True,
            },
        }
    }

    agents = config.values["agents"]
    agents["support_agent"] = {
        "enabled": True,
        "type": "general_assistant",
        "description": "Support assistant used as the task-execution primary agent.",
        "llm_profile": "local_reasoning",
        "prompt_profile": "general_assistant_v1",
    }
    agents["task_execution_agent"] = {
        "enabled": True,
        "type": "task_execution",
        "description": "Task-first assessment agent for visualization flow tests.",
        "llm_profile": "local_reasoning",
        "prompt_profile": "task_execution_v1",
    }
    return config


def _structured_dataset_envelope(dataset: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "tool_name": "reporting.query_metric_series",
        "summary": {
            "message": dataset["query_summary"],
            "item_count": dataset["row_count"],
            "truncated": dataset["truncated"],
        },
        "data": {"dataset": dataset},
        "errors": [],
        "meta": {
            "schema_version": dataset["schema_version"],
            "output_schema": "structured_dataset_v1",
            "dataset_id": dataset["dataset_id"],
        },
    }


def _reporting_error_envelope(
    *,
    code: str,
    message: str,
    summary: str,
    retryable: bool,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "ok": False,
        "tool_name": "reporting.query_metric_series",
        "summary": {
            "message": summary,
            "item_count": 0,
            "truncated": False,
        },
        "data": {},
        "errors": [
            {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            }
        ],
        "meta": {
            "schema_version": "1.0",
            "output_schema": "structured_dataset_v1",
        },
    }


def _build_reporting_mcp_adapter(
    *,
    execution_result: MCPToolCallResult,
) -> FakeMCPClientAdapter:
    return FakeMCPClientAdapter(
        discovered_tools=[
            MCPToolDefinition(
                name="reporting.query_metric_series",
                description="Reporting dataset query",
            )
        ],
        execution_results={
            "reporting.query_metric_series": execution_result,
        },
        endpoint="http://tooling.invalid/mcp",
    )


def _build_tool_gateway_context(
    *,
    config: FakeConfigurationView,
    trace_store: FakeTraceStore,
    tools,
) -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="local_user",
            session_id="session_reporting_gateway",
            message="Generate an income versus expense chart for the last 6 months.",
            usecase="default_chat",
            trace_id="trace-reporting-gateway-0001",
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=tools,
        trace=trace_store,
        policy=DefaultPolicyService(config),
        config=config,
        runtime_metadata={"agent_name": "chart_agent", "strategy_name": "direct_agent"},
    )


def _build_service() -> tuple[
    DefaultSessionService,
    VisualizationFlowLLMGateway,
    FakeToolGateway,
    FakeWorkflowStateStore,
    object,
]:
    config = _build_chart_config()
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    llm = VisualizationFlowLLMGateway(default_profile="local_reasoning")
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
    visualization_runtime = build_visualization_runtime(config)
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=tools,
        visualization_gateway=visualization_runtime.gateway,
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_session_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=runtime,
        policy_service=FakePolicyService(),
        visualization_artifact_store=visualization_runtime.artifact_store,
        clock=FakeClock(
            [
                datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 1, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 2, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 3, tzinfo=UTC),
            ]
        ),
    )
    return service, llm, tools, workflow_state, visualization_runtime.artifact_store


def _build_sqlite_chart_config(tmp_path: Path, *, prefer_inline: bool) -> FakeConfigurationView:
    config = _build_chart_config()
    app_config = config.values.setdefault("app", {})
    app_config["data_dir"] = tmp_path.as_posix()

    visualization = config.values.setdefault("visualization", {})
    artifact_store = visualization.setdefault("artifact_store", {})
    artifact_store["enabled"] = True
    artifact_store["provider"] = "sqlite"
    artifact_store["public_retrieval_enabled"] = True
    artifact_store["allow_reference_data_mode"] = True
    artifact_store["exact_followup_retrieval_enabled"] = True
    artifact_store["retrieval_endpoint"] = "/artifacts/{artifact_id}"
    artifact_store["sqlite"] = {
        "path": "visualization_artifacts.db",
        "create_parent_dirs": True,
        "initialize_schema": True,
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
        "busy_timeout_ms": 5000,
        "foreign_keys": True,
    }
    visualization["history_replay"] = {
        "enabled": True,
        "prefer_inline": prefer_inline,
        "max_artifacts_per_message": 3,
        "max_inline_artifact_bytes": 65536,
        "max_total_bytes_per_message": 131072,
    }
    return config


async def _build_sqlite_history_service(
    tmp_path: Path,
    *,
    prefer_inline: bool,
) -> tuple[
    DefaultSessionService,
    SqliteWorkflowStateStore,
    object,
]:
    config = _build_sqlite_chart_config(tmp_path, prefer_inline=prefer_inline)
    workflow_state = SqliteWorkflowStateStore(tmp_path / "workflow_state.db")
    await workflow_state.initialize()

    trace_store = FakeTraceStore()
    llm = VisualizationFlowLLMGateway(default_profile="local_reasoning")
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
    visualization_runtime = build_visualization_runtime(config)
    if visualization_runtime.artifact_store is not None and hasattr(
        visualization_runtime.artifact_store,
        "initialize",
    ):
        await visualization_runtime.artifact_store.initialize()

    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=tools,
        visualization_gateway=visualization_runtime.gateway,
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_session_settings(default_usecase="default_chat", history_enabled=True),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=runtime,
        policy_service=FakePolicyService(),
        visualization_artifact_store=visualization_runtime.artifact_store,
        clock=FakeClock(
            [
                datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
                datetime(2026, 7, 10, 13, 0, 1, tzinfo=UTC),
                datetime(2026, 7, 10, 13, 0, 2, tzinfo=UTC),
                datetime(2026, 7, 10, 13, 0, 3, tzinfo=UTC),
            ]
        ),
    )
    return service, workflow_state, visualization_runtime.artifact_store


def _build_task_execution_service() -> tuple[
    DefaultSessionService,
    TaskExecutionVisualizationFlowLLMGateway,
    FakeToolGateway,
    FakeWorkflowStateStore,
    object,
]:
    config = _build_task_execution_chart_config()
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    llm = TaskExecutionVisualizationFlowLLMGateway(default_profile="local_reasoning")
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
    visualization_runtime = build_visualization_runtime(config)
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=tools,
        visualization_gateway=visualization_runtime.gateway,
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_session_settings(default_usecase="task_execution_chat"),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=runtime,
        policy_service=FakePolicyService(),
        visualization_artifact_store=visualization_runtime.artifact_store,
        clock=FakeClock(
            [
                datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 1, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 2, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 3, tzinfo=UTC),
            ]
        ),
    )
    return service, llm, tools, workflow_state, visualization_runtime.artifact_store


def _build_fixture_task_execution_service(
    case: dict[str, object],
    *,
    llm: FakeLLMGateway | None = None,
) -> tuple[
    DefaultSessionService,
    FakeLLMGateway,
    FakeToolGateway,
    FakeWorkflowStateStore,
    object,
]:
    config = _build_task_execution_chart_config()
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    llm_gateway = llm or FixtureDrivenTaskExecutionVisualizationLLMGateway(
        case=case,
        default_profile="local_reasoning",
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
    visualization_runtime = build_visualization_runtime(config)
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm_gateway,
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=tools,
        visualization_gateway=visualization_runtime.gateway,
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_session_settings(default_usecase="task_execution_chat"),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=runtime,
        policy_service=FakePolicyService(),
        visualization_artifact_store=visualization_runtime.artifact_store,
        clock=FakeClock(
            [
                datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 1, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 2, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 3, tzinfo=UTC),
            ]
        ),
    )
    return service, llm_gateway, tools, workflow_state, visualization_runtime.artifact_store


async def _build_service_with_real_tool_gateway() -> tuple[
    DefaultSessionService,
    VisualizationFlowLLMGateway,
    FakeMCPClientAdapter,
    FakeWorkflowStateStore,
    object,
    FakeTraceStore,
]:
    config = _build_real_tooling_config()
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    llm = VisualizationFlowLLMGateway(default_profile="local_reasoning")
    adapter = _build_reporting_mcp_adapter(
        execution_result=MCPToolCallResult(
            mcp_tool_name="reporting.query_metric_series",
            status="completed",
            structured_content=_structured_dataset_envelope(DATASET_FIXTURE),
        )
    )
    tooling_runtime = build_tooling_runtime(config, mcp_adapter=adapter)
    await initialize_tooling_runtime(tooling_runtime)
    visualization_runtime = build_visualization_runtime(config)
    policy_service = DefaultPolicyService(config)
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=policy_service,
        tools=tooling_runtime.gateway,
        visualization_gateway=visualization_runtime.gateway,
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_session_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=runtime,
        policy_service=policy_service,
        visualization_artifact_store=visualization_runtime.artifact_store,
        clock=FakeClock(
            [
                datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 1, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 2, tzinfo=UTC),
                datetime(2026, 7, 10, 12, 0, 3, tzinfo=UTC),
            ]
        ),
    )
    return (
        service,
        llm,
        adapter,
        workflow_state,
        visualization_runtime.artifact_store,
        trace_store,
    )


@pytest.mark.asyncio
async def test_session_service_runs_real_chart_pipeline_and_persists_summary_only() -> None:
    service, llm, tools, workflow_state, artifact_store = _build_service()

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="Generate an income versus expense chart for the last 6 months.",
            session_id="session_vis_phase10",
            usecase="default_chat",
        ),
        context=_build_context(
            trace_id="trace-vis-phase10-0001",
            request_id="request-vis-phase10-0001",
        ),
    )

    assert result.answer == "Here is the income versus expense chart for the last 6 months."
    assert len(result.artifacts) == 1
    assert result.metadata["artifact_count"] == 1
    assert result.metadata["artifact_delivery_mode"] == "inline"
    assert result.metadata["context_summary_added"] is True
    assert tools.calls[0].tool_name == "reporting.query_metric_series"
    assert len(llm.requests) == 1

    saved_summary = workflow_state.states["session_vis_phase10"]["metadata"]["visualization_context"]["summaries"][0]
    artifact = result.artifacts[0]

    assert saved_summary["artifact_id"] == artifact["artifact_id"]
    assert saved_summary["chart_type"] == "grouped_bar"
    assert "data" not in saved_summary
    assert artifact["data"][2]["expense"] == 109400.0

    assert artifact_store is not None
    stored_artifact = await artifact_store.get_artifact(
        scope=build_visualization_artifact_scope(
            session_id="session_vis_phase10",
            user_id="local_user",
            scope=None,
        ),
        artifact_id=artifact["artifact_id"],
    )
    assert stored_artifact.artifact_id == artifact["artifact_id"]


@pytest.mark.asyncio
async def test_session_history_replay_survives_sqlite_restart_with_reference_artifacts(tmp_path) -> None:
    session_id = "session_vis_history_restart"
    service, workflow_state, artifact_store = await _build_sqlite_history_service(
        tmp_path,
        prefer_inline=False,
    )

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="Generate an income versus expense chart for the last 6 months.",
            session_id=session_id,
            usecase="default_chat",
        ),
        context=_build_context(
            trace_id="trace-vis-history-restart-0001",
            request_id="request-vis-history-restart-0001",
        ),
    )

    artifact_id = result.artifacts[0]["artifact_id"]
    saved = await workflow_state.load(session_id)
    saved_artifact = saved.state["conversation"]["messages"][-1]["artifacts"][0]

    assert saved_artifact["artifact_id"] == artifact_id
    assert saved_artifact["data_mode"] == "reference"
    assert saved_artifact["data_ref"] == f"/artifacts/{artifact_id}"

    first_history = await service.get_history(
        session_id=session_id,
        limit=10,
        context=_build_context(
            trace_id="trace-vis-history-restart-0002",
            request_id="request-vis-history-restart-0002",
            path=f"/sessions/{session_id}/history",
            method="GET",
        ),
    )

    assert first_history.messages[-1].artifacts == [saved_artifact]
    assert first_history.messages[-1].metadata["artifact_replay_status"] == "available"

    restarted_service, _restarted_workflow_state, restarted_artifact_store = (
        await _build_sqlite_history_service(tmp_path, prefer_inline=False)
    )
    restarted_history = await restarted_service.get_history(
        session_id=session_id,
        limit=10,
        context=_build_context(
            trace_id="trace-vis-history-restart-0003",
            request_id="request-vis-history-restart-0003",
            path=f"/sessions/{session_id}/history",
            method="GET",
        ),
    )

    assert restarted_history.messages[-1].artifacts == [saved_artifact]
    assert restarted_history.messages[-1].metadata["artifact_replay_status"] == "available"

    assert artifact_store is not None
    assert restarted_artifact_store is not None
    restarted_artifact = await restarted_artifact_store.get_artifact(
        scope=build_visualization_artifact_scope(
            session_id=session_id,
            user_id="local_user",
            scope=None,
        ),
        artifact_id=artifact_id,
    )

    assert restarted_artifact.artifact_id == artifact_id


@pytest.mark.asyncio
async def test_chart_followup_uses_summary_context_without_prompt_row_leak() -> None:
    service, llm, _tools, workflow_state, _artifact_store = _build_service()
    session_id = "session_vis_phase10_followup"

    first = await service.handle_chat(
        request=build_session_chat_request(
            message="Generate an income versus expense chart for the last 6 months.",
            session_id=session_id,
            usecase="default_chat",
        ),
        context=_build_context(
            trace_id="trace-vis-phase10-1001",
            request_id="request-vis-phase10-1001",
        ),
    )
    second = await service.handle_chat(
        request=build_session_chat_request(
            message="What was the expense in 2026-03-01?",
            session_id=session_id,
            usecase="default_chat",
        ),
        context=_build_context(
            trace_id="trace-vis-phase10-1002",
            request_id="request-vis-phase10-1002",
        ),
    )

    assert first.metadata["context_summary_id"] == first.artifacts[0]["artifact_id"]
    assert second.answer == "For 2026-03-01, expense was 109400."
    assert second.metadata["message_count_before"] == 2
    assert len(llm.requests) == 2

    followup_prompt = _prompt_text(llm.requests[1])
    artifact_id = first.artifacts[0]["artifact_id"]

    assert artifact_id in followup_prompt
    assert "dataset_id" not in followup_prompt
    assert '{"reporting_period": "2026-03-01", "income": 128900.0, "expense": 109400.0}' not in followup_prompt
    assert "rows" not in workflow_state.states[session_id]["metadata"]["visualization_context"]["summaries"][0]


@pytest.mark.asyncio
async def test_task_execution_chat_synthesizes_chart_data_and_answers_exact_followup() -> None:
    service, llm, tools, workflow_state, _artifact_store = _build_task_execution_service()
    session_id = "session_task_execution_chart"

    first = await service.handle_chat(
        request=build_session_chat_request(
            message=TASK_EXECUTION_FTEC_MESSAGE,
            session_id=session_id,
            usecase="task_execution_chat",
        ),
        context=_build_context(
            trace_id="trace-task-execution-chart-0001",
            request_id="request-task-execution-chart-0001",
        ),
    )

    assert first.answer == "Here is the projected investment value chart."
    assert len(first.artifacts) == 1
    assert first.artifacts[0]["data"][0]["projected_value"] == 10000.0
    assert tools.calls == []
    assert len(llm.requests) == 2

    final_point = first.artifacts[0]["data"][-1]
    final_date = final_point["date"]
    final_value = final_point["projected_value"]

    second = await service.handle_chat(
        request=build_session_chat_request(
            message=f"What is the projected value on {final_date}?",
            session_id=session_id,
            usecase="task_execution_chat",
        ),
        context=_build_context(
            trace_id="trace-task-execution-chart-0002",
            request_id="request-task-execution-chart-0002",
        ),
    )

    assert final_date in second.answer
    assert f"{final_value:.2f}" in second.answer
    assert second.metadata["message_count_before"] == 2
    assert tools.calls == []
    assert len(llm.requests) == 4

    followup_prompt = _prompt_text(llm.requests[3])
    artifact_id = first.artifacts[0]["artifact_id"]

    assert artifact_id in followup_prompt
    assert '{"date":' not in followup_prompt
    assert "rows" not in workflow_state.states[session_id]["metadata"]["visualization_context"]["summaries"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CHART_VALIDATION_CASES, ids=lambda case: str(case["chart_type"]))
async def test_task_execution_chat_generates_expected_visualization_for_fixture_prompt(
    case: dict[str, object],
) -> None:
    service, llm, tools, workflow_state, _artifact_store = _build_fixture_task_execution_service(case)
    session_id = f"session_task_execution_fixture_{case['chart_type']}"
    expected_artifact = _validation_case_artifact(case)

    result = await service.handle_chat(
        request=build_session_chat_request(
            message=_build_prompt_from_validation_case(case),
            session_id=session_id,
            usecase="task_execution_chat",
        ),
        context=_build_context(
            trace_id=f"trace-task-execution-fixture-{case['chart_type']}",
            request_id=f"request-task-execution-fixture-{case['chart_type']}",
        ),
    )

    assert result.answer == f"Here is the {str(case['chart_type']).replace('_', ' ')} chart."
    assert result.metadata["artifact_count"] == 1
    assert result.metadata["context_summary_added"] is True
    assert len(result.artifacts) == 1
    assert tools.calls == []
    assert [request.component for request in llm.requests] == [
        "agent.task_execution_agent",
        "agent.chart_agent",
    ]

    artifact = result.artifacts[0]
    assert artifact["type"] == "chart"
    assert artifact["chart_type"] == expected_artifact["chart_type"]
    assert artifact["title"] == expected_artifact["title"]
    assert artifact["description"] == expected_artifact["description"]
    assert artifact["renderer"] == expected_artifact["renderer"]
    assert artifact["spec_version"] == expected_artifact["spec_version"]
    assert artifact["data_mode"] == expected_artifact["data_mode"]
    assert artifact["data"] == expected_artifact["data"]
    assert artifact["warnings"] == expected_artifact["warnings"]

    expected_encoding = expected_artifact["encoding"]
    assert isinstance(expected_encoding, dict)
    for key, value in expected_encoding.items():
        assert artifact["encoding"][key] == value

    saved_summary = workflow_state.states[session_id]["metadata"]["visualization_context"]["summaries"][0]
    assert saved_summary["artifact_id"] == artifact["artifact_id"]
    assert saved_summary["chart_type"] == expected_artifact["chart_type"]


@pytest.mark.asyncio
async def test_task_execution_chat_forces_table_prompt_back_to_chart_agent_when_assessment_answers_directly() -> None:
    case = next(item for item in CHART_VALIDATION_CASES if str(item["chart_type"]) == "table")
    weak_llm = WeakAssessmentFixtureDrivenTaskExecutionVisualizationLLMGateway(
        case=case,
        default_profile="local_reasoning",
    )
    service, llm, tools, workflow_state, _artifact_store = _build_fixture_task_execution_service(
        case,
        llm=weak_llm,
    )
    session_id = "session_task_execution_explicit_table_prompt"

    result = await service.handle_chat(
        request=build_session_chat_request(
            message=_build_prompt_from_validation_case(case),
            session_id=session_id,
            usecase="task_execution_chat",
        ),
        context=_build_context(
            trace_id="trace-task-execution-explicit-table-prompt",
            request_id="request-task-execution-explicit-table-prompt",
        ),
    )

    assert result.answer == "Here is the table chart."
    assert result.metadata["response_mode"] == "planned_execution"
    assert result.metadata["visualization_intent"] is True
    assert result.metadata["artifact_count"] == 1
    assert result.artifacts[0]["chart_type"] == "table"
    assert tools.calls == []
    assert [request.component for request in llm.requests] == [
        "agent.task_execution_agent",
        "agent.chart_agent",
    ]

    saved_summary = workflow_state.states[session_id]["metadata"]["visualization_context"]["summaries"][0]
    assert saved_summary["chart_type"] == "table"


@pytest.mark.asyncio
async def test_task_execution_chat_forces_table_prompt_back_to_chart_agent_when_assessment_parse_fails() -> None:
    case = next(item for item in CHART_VALIDATION_CASES if str(item["chart_type"]) == "table")
    broken_llm = BrokenAssessmentFixtureDrivenTaskExecutionVisualizationLLMGateway(
        case=case,
        default_profile="local_reasoning",
    )
    service, llm, tools, workflow_state, _artifact_store = _build_fixture_task_execution_service(
        case,
        llm=broken_llm,
    )
    session_id = "session_task_execution_table_prompt_parse_failure"

    result = await service.handle_chat(
        request=build_session_chat_request(
            message=_build_prompt_from_validation_case(case),
            session_id=session_id,
            usecase="task_execution_chat",
        ),
        context=_build_context(
            trace_id="trace-task-execution-table-prompt-parse-failure",
            request_id="request-task-execution-table-prompt-parse-failure",
        ),
    )

    assert result.answer == "Here is the table chart."
    assert result.metadata["assessment_source"] == "heuristic"
    assert result.metadata["response_mode"] == "planned_execution"
    assert result.metadata["visualization_intent"] is True
    assert result.metadata["artifact_count"] == 1
    assert result.artifacts[0]["chart_type"] == "table"
    assert tools.calls == []
    assert [request.component for request in llm.requests] == [
        "agent.task_execution_agent",
        "agent.chart_agent",
    ]

    saved_summary = workflow_state.states[session_id]["metadata"]["visualization_context"]["summaries"][0]
    assert saved_summary["chart_type"] == "table"


@pytest.mark.asyncio
async def test_task_execution_chat_generates_pie_from_percentage_split_prompt() -> None:
    case = _build_percentage_split_case()
    service, llm, tools, workflow_state, _artifact_store = _build_fixture_task_execution_service(case)
    session_id = "session_task_execution_percentage_split_pie"

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="draw a pie chart showing 77% for 'yes' and the rest as 'no'",
            session_id=session_id,
            usecase="task_execution_chat",
        ),
        context=_build_context(
            trace_id="trace-task-execution-percentage-split-pie",
            request_id="request-task-execution-percentage-split-pie",
        ),
    )

    assert result.answer == "Here is the pie chart."
    assert result.metadata["artifact_count"] == 1
    assert result.metadata["context_summary_added"] is True
    assert len(result.artifacts) == 1
    assert tools.calls == []
    assert [request.component for request in llm.requests] == [
        "agent.task_execution_agent",
        "agent.chart_agent",
    ]

    artifact = result.artifacts[0]
    assert artifact["chart_type"] == "pie"
    assert artifact["title"] == "Yes vs No"
    assert artifact["encoding"] == {"category": "label", "value": "value"}
    assert artifact["data"] == [
        {"label": "yes", "value": 77},
        {"label": "no", "value": 23},
    ]

    saved_summary = workflow_state.states[session_id]["metadata"]["visualization_context"]["summaries"][0]
    assert saved_summary["artifact_id"] == artifact["artifact_id"]
    assert saved_summary["chart_type"] == "pie"


@pytest.mark.asyncio
async def test_session_service_uses_real_tool_gateway_and_mcp_adapter_for_chart_data() -> None:
    service, llm, adapter, workflow_state, artifact_store, trace_store = (
        await _build_service_with_real_tool_gateway()
    )

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="Generate an income versus expense chart for the last 6 months.",
            session_id="session_vis_phase6_gateway",
            usecase="default_chat",
        ),
        context=_build_context(
            trace_id="trace-vis-phase6-gateway-0001",
            request_id="request-vis-phase6-gateway-0001",
        ),
    )

    assert result.answer == "Here is the income versus expense chart for the last 6 months."
    assert len(result.artifacts) == 1
    assert len(llm.requests) == 1
    assert len(adapter.call_requests) == 1
    assert adapter.call_requests[0].mcp_tool_name == "reporting.query_metric_series"
    assert adapter.call_requests[0].trace_id == "trace-vis-phase6-gateway-0001"
    assert adapter.call_requests[0].session_id == "session_vis_phase6_gateway"

    artifact = result.artifacts[0]
    saved_summary = workflow_state.states["session_vis_phase6_gateway"]["metadata"][
        "visualization_context"
    ]["summaries"][0]

    assert artifact["data"][2]["expense"] == 109400.0
    assert "ok" not in artifact
    assert "errors" not in artifact
    assert "data" not in saved_summary
    assert "rows" not in saved_summary

    assert artifact_store is not None
    stored_artifact = await artifact_store.get_artifact(
        scope=build_visualization_artifact_scope(
            session_id="session_vis_phase6_gateway",
            user_id="local_user",
            scope=None,
        ),
        artifact_id=artifact["artifact_id"],
    )
    assert stored_artifact.artifact_id == artifact["artifact_id"]

    tool_events = [
        event for event in trace_store.events if event.tool_name == "reporting.query_metric_series"
    ]
    assert [event.event_type for event in tool_events] == [
        TOOL_CALL_STARTED,
        TOOL_CALL_COMPLETED,
    ]
    assert "109400.0" not in str(tool_events[-1].payload)
    assert "rows" not in str(tool_events[-1].payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("envelope", "expected_status", "expected_code"),
    [
        (QUERY_ERROR_FIXTURE, "failed", "unsupported_metric"),
        (
            _reporting_error_envelope(
                code="timeout",
                message="Reporting provider timed out.",
                summary="The reporting provider timed out before it returned a dataset.",
                retryable=True,
            ),
            "timeout",
            "timeout",
        ),
        (
            _reporting_error_envelope(
                code="unauthorized_scope",
                message="Reporting scope filters did not match the approved provider scope.",
                summary="The requested reporting scope is not authorized.",
                retryable=False,
                details={"field": "business_unit", "value": "other"},
            ),
            "failed",
            "unauthorized_scope",
        ),
    ],
)
async def test_real_tool_gateway_normalizes_reporting_error_envelopes(
    envelope: dict[str, object],
    expected_status: str,
    expected_code: str,
) -> None:
    config = _build_real_tooling_config()
    trace_store = FakeTraceStore()
    adapter = _build_reporting_mcp_adapter(
        execution_result=MCPToolCallResult(
            mcp_tool_name="reporting.query_metric_series",
            status="completed",
            structured_content=envelope,
        )
    )
    tooling_runtime = build_tooling_runtime(config, mcp_adapter=adapter)
    await initialize_tooling_runtime(tooling_runtime)
    context = _build_tool_gateway_context(
        config=config,
        trace_store=trace_store,
        tools=tooling_runtime.gateway,
    )

    result = await tooling_runtime.gateway.execute(
        ToolExecutionRequest(
            tool_name="reporting.query_metric_series",
            arguments={
                "metric_names": ["income"],
                "dimension": "reporting_period",
                "granularity": "month",
                "limit": 6,
            },
            scopes=ToolScopes(project_id="bb2"),
        ),
        context,
    )

    assert len(adapter.call_requests) == 1
    assert result.status == expected_status
    assert result.structured_content is None
    assert result.error_detail is not None
    assert result.error_detail.code == expected_code
    assert result.summary is not None
    assert result.summary.safe_message is not None