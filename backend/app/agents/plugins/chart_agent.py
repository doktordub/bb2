"""Chart-focused agent plugin for controlled visualization generation and follow-ups."""

from __future__ import annotations

from calendar import monthrange
import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents.errors import (
    AgentCancelledError,
    AgentConfigurationError,
    AgentInputValidationError,
    AgentOutputParseError,
    AgentToolIntentError,
    normalize_agent_error,
)
from app.agents.models import AgentCapabilities, AgentOutputItem, AgentRunRequest, AgentRunResult, AgentStreamEvent
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.policy import require_capability_allowed, require_capability_policy
from app.agents.prompts import limit_prompt_sections
from app.agents.result_builder import build_run_result, build_usage_summary
from app.agents.stream_mapping import build_cancelled_event, build_completed_event, build_failed_event, build_started_event
from app.agents.trace_helpers import build_llm_trace_summary, build_prompt_trace_summary, build_request_trace_summary, build_result_trace_summary
from app.config.view import get_visualization_settings
from app.contracts.context import OrchestrationContext
from app.contracts.llm import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMResponseFormat,
    LLMToolCall,
    LLMToolCallFunction,
    LLMToolChoice,
    LLMToolDefinition,
    LLMToolFunction,
)
from app.contracts.memory import MemoryResult, MemoryScope, MemorySearchRequest
from app.contracts.tools import ToolExecutionRequest, ToolExecutionResult, ToolScopes
from app.memory.redaction import truncate_text
from app.orchestration.models import sanitize_metadata
from app.orchestration.prompt_inputs import PromptSection
from app.visualization.chart_summary_builder import build_chart_context_contribution
from app.visualization.context_selector import collect_chart_summaries, select_chart_summaries_for_prompt
from app.visualization.errors import ChartArtifactNotFoundError, ChartDataMissingError
from app.visualization.gateway import VisualizationGateway, build_visualization_gateway
from app.visualization.models import ChartContextSummary, ChartDataSlice, ChartRequest, VisualizationContext

_AGENT_LLM_COMPLETED = "agent_llm_completed"
_AGENT_LLM_STARTED = "agent_llm_started"
_AGENT_PROMPT_BUILT = "agent_prompt_built"
_CHART_DATA_RESOLUTION_COMPLETED = "chart_data_resolution_completed"
_CHART_DATA_RESOLUTION_STARTED = "chart_data_resolution_started"
_DETERMINISTIC_DATA_SYNTHESIZED = "deterministic_data_synthesized"
_DEFAULT_MAX_CONTEXT_BYTES = 24000
_DEFAULT_MAX_CONTEXT_ITEMS = 4
_DEFAULT_MAX_TOOL_ROWS = 500
_INLINE_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_MARKDOWN_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
_TABLE_CURRENCY_SYMBOLS = "$"
_COMPOUND_GROWTH_AMOUNT_RE = re.compile(r"\$\s*(?P<amount>\d[\d,]*(?:\.\d+)?)")
_COMPOUND_GROWTH_RATE_RE = re.compile(
    r"(?P<rate>-?\d+(?:\.\d+)?)\s*%\s*(?:annual|yearly|per\s+year|growth|return|cagr)?",
    re.IGNORECASE,
)
_COMPOUND_GROWTH_HORIZON_RE = re.compile(
    r"(?:(?:over|for|across|during)\s+(?:the\s+next\s+)?)?(?P<count>\d{1,3})\s*[- ]?(?P<unit>years?|yrs?|months?|mos?)\b",
    re.IGNORECASE,
)
_COMPOUND_GROWTH_ASSET_RE = re.compile(r"\b(?:into|in|for)\s+(?P<asset>[A-Z]{2,10})\b")
_PERCENTAGE_SPLIT_RE = re.compile(
    r"(?P<first_value>\d+(?:\.\d+)?)\s*%\s*(?:for\s+)?['\"]?(?P<first_label>[^'\"\n]+?)['\"]?\s+and\s+(?:the\s+)?rest\s+(?:as|for)\s+['\"]?(?P<second_label>[^'\"\n?.!,]+?)['\"]?(?:[?.!,]|$)",
    re.IGNORECASE,
)
_PROMPT_TITLE_RE = re.compile(r'\btitled\s+"(?P<title>[^"\n]+)"', re.IGNORECASE)
_COMPOUND_GROWTH_HINTS = (
    "investment",
    "invest",
    "growth rate",
    "annual growth",
    "projected value",
    "projection",
    "forecast",
    "compound",
)
_MAX_COMPOUND_GROWTH_YEARS = 60
_MAX_COMPOUND_GROWTH_MONTHS = 240
_SUPPORTED_SUMMARY_QUESTION_TYPES = frozenset(
    {
        "comparison",
        "extrema_lookup",
        "overview",
        "summary",
        "trend",
        "trend_summary",
        "what_does_this_show",
    }
)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_text_list(values: Sequence[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _optional_text(value)
        if item is None or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return normalized


def _normalized_question_type(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    return text.lower().replace("-", "_").replace(" ", "_")


class _ChartIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: Literal["generate_chart", "chart_followup", "missing_data", "not_chart"]
    chart_type: str | None = None
    title: str | None = None
    description: str | None = None
    x_field: str | None = None
    y_fields: list[str] = Field(default_factory=list)
    category_field: str | None = None
    series_field: str | None = None
    value_field: str | None = None
    time_field: str | None = None
    size_field: str | None = None
    start_field: str | None = None
    end_field: str | None = None
    requires_data: bool = False
    data_source_hint: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    answer: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    referenced_artifact_id: str | None = None
    question_type: str | None = None
    requires_exact_data: bool = False
    required_fields: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "chart_type",
        "title",
        "description",
        "x_field",
        "category_field",
        "series_field",
        "value_field",
        "time_field",
        "size_field",
        "start_field",
        "end_field",
        "data_source_hint",
        "answer",
        "tool_name",
        "referenced_artifact_id",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        return _optional_text(value)

    @field_validator("question_type", mode="before")
    @classmethod
    def _normalize_question_type(cls, value: object) -> str | None:
        return _normalized_question_type(value)

    @field_validator("y_fields", "missing_information", "required_fields", mode="before")
    @classmethod
    def _normalize_list_fields(cls, value: object) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
            return []
        return _normalize_text_list(value)

    @field_validator("tool_arguments", "filters", mode="before")
    @classmethod
    def _normalize_mapping_fields(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        return sanitize_metadata(dict(value))


class _DatasetColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    data_type: Literal["string", "integer", "number", "boolean", "date", "datetime"]
    nullable: bool = True
    semantic_role: Literal[
        "dimension",
        "metric",
        "time",
        "category",
        "series",
        "identifier",
        "other",
    ] = "other"
    unit: str | None = None

    @field_validator("name")
    @classmethod
    def _require_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Column name must not be empty.")
        return normalized

    @field_validator("unit", mode="before")
    @classmethod
    def _normalize_unit(cls, value: object) -> str | None:
        return _optional_text(value)


class _StructuredDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str
    columns: list[_DatasetColumn]
    rows: list[dict[str, Any]]
    row_count: int = Field(ge=0)
    total_row_count: int | None = Field(default=None, ge=0)
    truncated: bool = False
    source: str
    query_summary: str
    time_range: dict[str, str] | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dataset_id", "source", "query_summary")
    @classmethod
    def _require_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dataset text fields must not be empty.")
        return normalized

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_warnings(cls, value: object) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
            return []
        return _normalize_text_list(value)

    @field_validator("provenance", mode="before")
    @classmethod
    def _normalize_provenance(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        return sanitize_metadata(dict(value))

    @model_validator(mode="after")
    def _validate_rows(self) -> "_StructuredDatasetResponse":
        if self.row_count != len(self.rows):
            raise ValueError("row_count must match the number of rows.")

        column_map = {column.name: column for column in self.columns}
        if not column_map:
            raise ValueError("Dataset columns must not be empty.")

        for index, row in enumerate(self.rows):
            if not isinstance(row, dict):
                raise ValueError(f"Row {index + 1} must be an object.")
            unknown_keys = sorted(set(row) - set(column_map))
            if unknown_keys:
                raise ValueError(
                    f"Row {index + 1} contains fields not declared in columns: {', '.join(unknown_keys)}"
                )
            for column in self.columns:
                value = row.get(column.name)
                if value is None:
                    if not column.nullable:
                        raise ValueError(
                            f"Column '{column.name}' is not nullable but row {index + 1} is missing a value."
                        )
                    continue
                if not _value_matches_dataset_type(value, column.data_type):
                    raise ValueError(
                        f"Column '{column.name}' in row {index + 1} does not match declared type '{column.data_type}'."
                    )
        return self


@dataclass(frozen=True, slots=True)
class _ResolvedChartData:
    rows: tuple[dict[str, Any], ...]
    source: Literal[
        "deterministic_synthesis",
        "memory",
        "tool",
        "unknown",
        "uploaded_file",
        "user_provided",
        "workflow_state",
    ]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    memory_searches: int = 0
    tool_calls: int = 0


@dataclass(frozen=True, slots=True)
class _CompoundGrowthProjection:
    initial_amount: float
    annual_growth_rate_pct: float
    horizon_count: int
    horizon_unit: Literal["month", "year"]
    asset_label: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class _ChartOutcome:
    answer: str
    output_items: tuple[AgentOutputItem, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_searches: int = 0
    tool_calls: int = 0


class ChartAgent(BaseLlmAgent):
    """Controlled chart-generation agent that uses backend gateways only."""

    type = "chart_agent"
    description = "Generates validated chart artifacts and handles chart follow-up questions."
    display_name = "Chart Agent"
    supported_strategies: tuple[str, ...] = ("direct_agent", "tool_assisted", "router")
    stream_llm_deltas = False
    structured_capabilities = AgentCapabilities(
        answer=True,
        review=False,
        stream=True,
        memory_read=True,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=False,
        tool_execute=True,
        self_managed_memory=False,
        self_managed_tools=True,
    )
    metadata = {"built_in": True, "mode": "visualization"}

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AgentRunResult:
        require_capability_allowed(self.structured_capabilities, "answer", agent_name=self.name)
        await require_capability_policy(
            context,
            request=request,
            capability_name="answer",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type},
        )
        self._require_llm_call_budget()

        started_at = perf_counter()
        llm_profile = self.resolve_llm_profile(request)
        await self._record_trace(
            context=context,
            request=request,
            event_name="agent_started",
            status="started",
            llm_profile=llm_profile,
            payload=build_request_trace_summary(request, agent_name=self.name),
        )

        try:
            await self._require_invoke_policy(context=context, request=request)
            messages = self.build_prompt_messages_for_request(request=request, context=context)
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_PROMPT_BUILT,
                llm_profile=llm_profile,
                payload=build_prompt_trace_summary(
                    request,
                    agent_name=self.name,
                    prompt_profile=self.prompt_profile,
                    message_count=len(messages),
                ),
            )

            await self._require_llm_policy(
                context=context,
                request=request,
                llm_profile=llm_profile,
                stream=False,
            )
            llm_request = self.build_llm_request(
                messages=messages,
                request=request,
                llm_profile=llm_profile,
                stream=False,
            )
            llm_request = self._finalize_llm_request(
                llm_request,
                request=request,
                context=context,
                llm_profile=llm_profile,
            )
            llm_started_at = perf_counter()
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_LLM_STARTED,
                status="started",
                llm_profile=llm_profile,
                payload=build_llm_trace_summary(
                    llm_profile=llm_profile,
                    output_kind=self.output_kind,
                ),
            )
            response = await context.llm.complete(llm_request, context)
            llm_duration_ms = int((perf_counter() - llm_started_at) * 1000)
            response_profile = response.profile or llm_profile
            if response.tool_calls:
                outcome = await self._resolve_native_tool_outcome(
                    response=response,
                    request=request,
                    context=context,
                )
            else:
                try:
                    parsed = self._parse_response_payload(response.text)
                except AgentOutputParseError:
                    outcome = await self._recover_outcome_from_parse_failure(
                        request=request,
                        context=context,
                    )
                    if outcome is None:
                        raise
                else:
                    outcome = await self._resolve_outcome(parsed=parsed, request=request, context=context)
            usage = build_usage_summary(
                llm_calls=1,
                memory_searches=outcome.memory_searches,
                tool_calls=outcome.tool_calls,
                input_chars=sum(len(message.content) for message in messages if isinstance(message.content, str)),
                output_chars=len(response.text),
            )
            result = build_run_result(
                status="completed",
                answer=outcome.answer,
                agent_name=self.name,
                llm_profile=response_profile,
                usage=usage,
                output_items=outcome.output_items,
                artifacts=outcome.metadata.get("artifacts", ()),
                context_contributions=outcome.metadata.get("context_contributions", ()),
                metadata={
                    **outcome.metadata,
                    **self._response_metadata(response),
                },
            )

            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_LLM_COMPLETED,
                llm_profile=response_profile,
                duration_ms=float(llm_duration_ms),
                payload=build_llm_trace_summary(
                    llm_profile=response_profile,
                    output_kind=self.output_kind,
                    duration_ms=llm_duration_ms,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                ),
            )
            await self._record_trace(
                context=context,
                request=request,
                event_name="agent_completed",
                llm_profile=response_profile,
                duration_ms=float(int((perf_counter() - started_at) * 1000)),
                payload={
                    **build_result_trace_summary(result),
                    "duration_ms": int((perf_counter() - started_at) * 1000),
                },
            )
            return result
        except BaseException as exc:
            normalized = normalize_agent_error(exc)
            await self._record_failure(
                context=context,
                request=request,
                llm_profile=llm_profile,
                error=normalized,
                duration_ms=float(int((perf_counter() - started_at) * 1000)),
            )
            if normalized is exc:
                raise
            raise normalized from exc

    async def stream(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        yield build_started_event(
            self.name,
            metadata={
                "agent_type": self.type,
                "llm_profile": request.llm_profile or self.default_llm_profile,
            },
        )
        try:
            result = await self.run_structured(request=request, context=context)
        except BaseException as exc:
            normalized = normalize_agent_error(exc)
            if isinstance(normalized, AgentCancelledError):
                yield build_cancelled_event(self.name)
                return
            yield build_failed_event(self.name, error=normalized.to_detail())
            return
        yield build_completed_event(self.name, result=result)

    def build_system_prompt(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> str:
        del request
        del context
        return (
            "You are the backend chart agent. Detect chart-generation and chart follow-up requests, "
            "return JSON only, and use backend gateways as the source of truth. Never invent numeric "
            "business values, never return frontend code, and never place full datasets into summary-style "
            "follow-up context. If data is missing, ask for the exact fields required."
        )

    def build_extra_prompt_sections(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[PromptSection, ...]:
        settings = self._visualization_settings(context)
        sections: list[PromptSection] = [
            PromptSection(
                title="Supported chart types",
                body="\n".join(f"- {chart_type}" for chart_type in settings.allowed_chart_types),
            ),
            PromptSection(
                title="Data resolution priority",
                body=(
                    "1. Explicit user-provided structured values\n"
                    "2. Relevant workflow-state data already present in the session\n"
                    "3. Approved uploaded-file ingestion results already provided by the backend\n"
                    "4. Approved memory retrieval\n"
                    "5. Approved logical tool call through the backend tool gateway"
                ),
            ),
        ]

        summaries = self._select_prompt_summaries(request=request, context=context)
        if summaries:
            summary_sections = [
                PromptSection(
                    title=f"Known chart summary {index + 1}",
                    body=self._render_summary_for_prompt(summary),
                )
                for index, summary in enumerate(summaries)
            ]
            sections.extend(
                limit_prompt_sections(
                    summary_sections,
                    max_items=getattr(self.context_policy, "max_context_items", _DEFAULT_MAX_CONTEXT_ITEMS),
                    max_chars=getattr(self.context_policy, "max_context_bytes", _DEFAULT_MAX_CONTEXT_BYTES),
                )
            )

        allowed_tools = self._allowed_tool_names(request)
        if allowed_tools:
            sections.append(
                PromptSection(
                    title="Allowed logical backend tools",
                    body="\n".join(f"- {tool_name}" for tool_name in allowed_tools),
                )
            )

        sections.append(
            PromptSection(
                title="Response contract",
                body=(
                    "Return JSON only. Use one of these intents: generate_chart, chart_followup, "
                    "missing_data, not_chart. For generate_chart include chart_type, title, optional "
                    "description, x_field, y_fields, category_field, series_field, value_field, time_field, "
                    "optional size_field, optional start_field, optional end_field, requires_data, "
                    "data_source_hint, optional tool_name, optional tool_arguments, and a short answer. "
                    "For chart_followup include referenced_artifact_id when known, question_type, "
                    "requires_exact_data, required_fields, filters, and a short answer only if no retrieval is "
                    "needed. For missing_data include missing_information and a concrete user-facing answer."
                ),
            )
        )
        sections.append(
            PromptSection(
                title="Rules",
                body=(
                    "Prefer summary-only follow-ups when a chart summary is sufficient. Use exact retrieval only "
                    "when the question needs specific values or rows. Never output unsupported chart types as if "
                    "they succeeded; instead list allowed alternatives."
                ),
            )
        )
        return tuple(sections)

    def build_llm_request(
        self,
        *,
        messages: Sequence[LLMMessage],
        request: AgentRunRequest,
        llm_profile: str,
        stream: bool,
    ) -> LLMRequest:
        llm_request = super().build_llm_request(
            messages=messages,
            request=request,
            llm_profile=llm_profile,
            stream=stream,
        )
        llm_request.response_format = LLMResponseFormat(
            type="json_object",
            schema_name="chart_agent_contract",
            strict=True,
        )
        return llm_request

    def _finalize_llm_request(
        self,
        llm_request: LLMRequest,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
        llm_profile: str,
    ) -> LLMRequest:
        llm_request = super()._finalize_llm_request(
            llm_request,
            request=request,
            context=context,
            llm_profile=llm_profile,
        )

        allowed_tools = self._allowed_tool_names(request)
        if not allowed_tools:
            return llm_request
        if self._profile_supports_tool_calling(context, llm_profile) is not True:
            return llm_request

        llm_request.tools = self._build_native_tool_definitions(
            allowed_tools,
            context=context,
        )
        llm_request.tool_choice = LLMToolChoice(type="auto")
        llm_request.metadata = sanitize_metadata(
            {
                **llm_request.metadata,
                "tool_calling_mode": "native_optional",
                "tool_count": len(llm_request.tools),
            }
        )
        return llm_request

    def _parse_response_payload(self, text: str) -> _ChartIntentPayload:
        normalized_text = text.strip()
        if not normalized_text:
            raise AgentOutputParseError("Chart agent returned an empty response.")
        payload = self._parse_response_mapping(normalized_text)
        if payload is None:
            raise AgentOutputParseError("Chart agent response was not valid JSON.")
        if not isinstance(payload, Mapping):
            raise AgentOutputParseError("Chart agent response must be a JSON object.")
        try:
            return _ChartIntentPayload.model_validate(payload)
        except ValidationError as exc:
            raise AgentOutputParseError("Chart agent response did not match the expected contract.") from exc

    def _parse_response_mapping(self, text: str) -> dict[str, Any] | None:
        payload = self._try_parse_json_text(text)
        if isinstance(payload, Mapping):
            return dict(payload)

        for block in _INLINE_JSON_BLOCK_RE.findall(text):
            payload = self._try_parse_json_text(block)
            if isinstance(payload, Mapping):
                return dict(payload)

        for payload in _iter_embedded_json_payloads(text):
            if isinstance(payload, Mapping):
                return dict(payload)

        return None

    async def _resolve_outcome(
        self,
        *,
        parsed: _ChartIntentPayload,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ChartOutcome:
        if parsed.intent == "not_chart":
            answer = parsed.answer or "This request does not appear to require a chart."
            return _ChartOutcome(
                answer=self.normalize_response_text(answer)[0],
                metadata={"response_mode": "not_chart", "chart_intent": parsed.intent},
            )

        if parsed.intent == "missing_data":
            answer = parsed.answer or self._missing_data_answer(parsed)
            return _ChartOutcome(
                answer=self.normalize_response_text(answer)[0],
                metadata={
                    "response_mode": "missing_data",
                    "chart_intent": parsed.intent,
                    "missing_information": list(parsed.missing_information),
                },
            )

        if parsed.intent == "chart_followup":
            return await self._handle_followup(parsed=parsed, request=request, context=context)

        return await self._handle_chart_generation(parsed=parsed, request=request, context=context)

    async def _resolve_native_tool_outcome(
        self,
        *,
        response: LLMResponse,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ChartOutcome:
        parsed = self._build_native_tool_payload(
            response.tool_calls,
            request=request,
            context=context,
        )
        settings = self._visualization_settings(context)
        normalized_chart_type = self._resolve_requested_chart_type(
            parsed_chart_type=parsed.chart_type,
            message=request.message,
            settings=settings,
        )
        if normalized_chart_type is None:
            raise AgentToolIntentError("Chart generation requires a chart_type.")

        await self._record_chart_resolution_event(
            context=context,
            request=request,
            event_name=_CHART_DATA_RESOLUTION_STARTED,
            payload={
                "requested_chart_type": normalized_chart_type,
                "available_tools": list(self._allowed_tool_names(request)),
                "tool_calling_mode": "native",
            },
            status="started",
        )
        local_resolved = self._resolve_local_chart_data(request=request, context=context)
        if local_resolved is not None:
            return await self._build_chart_generation_outcome(
                parsed=parsed,
                normalized_chart_type=normalized_chart_type,
                resolved=local_resolved,
                request=request,
                context=context,
                tool_calling_mode="native",
            )

        resolved = await self._execute_tool_for_rows(
            parsed=parsed,
            request=request,
            context=context,
        )
        if resolved is None:
            raise AgentToolIntentError("Chart agent could not resolve data for the requested native tool call.")

        return await self._build_chart_generation_outcome(
            parsed=parsed,
            normalized_chart_type=normalized_chart_type,
            resolved=resolved,
            request=request,
            context=context,
            tool_calling_mode="native",
        )

    async def _handle_chart_generation(
        self,
        *,
        parsed: _ChartIntentPayload,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ChartOutcome:
        settings = self._visualization_settings(context)
        normalized_chart_type = self._resolve_requested_chart_type(
            parsed_chart_type=parsed.chart_type,
            message=request.message,
            settings=settings,
        )
        if normalized_chart_type is None:
            raise AgentInputValidationError("Chart generation requires a chart_type.")
        if normalized_chart_type not in settings.allowed_chart_types:
            answer = (
                f"I cannot generate a {parsed.chart_type or normalized_chart_type} chart here. "
                f"Supported chart types include {', '.join(settings.allowed_chart_types[:8])}."
            )
            return _ChartOutcome(
                answer=answer,
                metadata={
                    "response_mode": "unsupported_chart_type",
                    "chart_intent": parsed.intent,
                    "requested_chart_type": parsed.chart_type,
                    "supported_chart_types": list(settings.allowed_chart_types),
                },
            )

        await self._record_chart_resolution_event(
            context=context,
            request=request,
            event_name=_CHART_DATA_RESOLUTION_STARTED,
            payload={
                "requested_chart_type": normalized_chart_type,
                "available_tools": list(self._allowed_tool_names(request)),
            },
            status="started",
        )

        resolved = await self._resolve_chart_data(
            parsed=parsed,
            request=request,
            context=context,
        )
        if resolved is None:
            answer = parsed.answer or self._missing_data_answer(parsed)
            return _ChartOutcome(
                answer=answer,
                metadata={
                    "response_mode": "missing_data",
                    "chart_intent": parsed.intent,
                    "missing_information": list(parsed.missing_information),
                },
            )

        return await self._build_chart_generation_outcome(
            parsed=parsed,
            normalized_chart_type=normalized_chart_type,
            resolved=resolved,
            request=request,
            context=context,
        )

    async def _recover_outcome_from_parse_failure(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ChartOutcome | None:
        resolved = self._resolve_local_chart_data(request=request, context=context)
        if resolved is None:
            return None

        settings = self._visualization_settings(context)
        normalized_chart_type = self._resolve_requested_chart_type(
            parsed_chart_type=None,
            message=request.message,
            settings=settings,
        )
        if normalized_chart_type is None or normalized_chart_type not in settings.allowed_chart_types:
            return None

        payload: dict[str, Any] = {
            "intent": "generate_chart",
            "chart_type": normalized_chart_type,
            "requires_data": True,
            "data_source_hint": resolved.source,
            "answer": f"Here is the {normalized_chart_type.replace('_', ' ')} chart.",
        }
        inferred_title = _infer_chart_title_from_message(request.message)
        if inferred_title is not None:
            payload["title"] = inferred_title

        parsed = _ChartIntentPayload.model_validate(payload)
        return await self._build_chart_generation_outcome(
            parsed=parsed,
            normalized_chart_type=normalized_chart_type,
            resolved=resolved,
            request=request,
            context=context,
        )

    async def _build_chart_generation_outcome(
        self,
        *,
        parsed: _ChartIntentPayload,
        normalized_chart_type: str,
        resolved: _ResolvedChartData,
        request: AgentRunRequest,
        context: OrchestrationContext,
        tool_calling_mode: str | None = None,
    ) -> _ChartOutcome:
        visualization_context = self._build_visualization_context(request=request, context=context)
        gateway = self._resolve_visualization_gateway(context=context)
        chart_request = self._build_chart_request(
            parsed=parsed,
            normalized_chart_type=normalized_chart_type,
            resolved=resolved,
            fallback_title=_infer_chart_title_from_message(request.message),
        )
        envelope = await gateway.build_visualization(
            chart_request,
            list(resolved.rows),
            visualization_context,
            metadata={
                "source": resolved.source,
                "source_agent": self.name,
                **resolved.metadata,
            },
            warnings=list(resolved.warnings),
        )
        contribution = build_chart_context_contribution(envelope.context_summary)
        answer = parsed.answer or f"Here is the {normalized_chart_type.replace('_', ' ')} chart."

        if resolved.source == "deterministic_synthesis":
            await self._record_chart_resolution_event(
                context=context,
                request=request,
                event_name=_DETERMINISTIC_DATA_SYNTHESIZED,
                payload={
                    **resolved.metadata,
                    "chart_type": normalized_chart_type,
                    "row_count": len(resolved.rows),
                },
            )

        await self._record_chart_resolution_event(
            context=context,
            request=request,
            event_name=_CHART_DATA_RESOLUTION_COMPLETED,
            payload={
                "chart_type": normalized_chart_type,
                "data_source": resolved.source,
                "row_count": len(resolved.rows),
                "tool_calling_mode": tool_calling_mode,
            },
        )
        metadata = {
            "response_mode": "chart_generated",
            "chart_intent": parsed.intent,
            "data_source": resolved.source,
            "artifact_count": 1,
            "context_contribution_count": 1,
            "artifacts": [envelope.artifact.model_dump(mode="python")],
            "context_contributions": [contribution.model_dump(mode="python")],
        }
        if tool_calling_mode is not None:
            metadata["tool_calling_mode"] = tool_calling_mode

        return _ChartOutcome(
            answer=self.normalize_response_text(answer)[0],
            output_items=(
                AgentOutputItem(
                    type="chart_artifact",
                    data=envelope.artifact.model_dump(mode="python"),
                    metadata={
                        "artifact_id": envelope.artifact.artifact_id,
                        "chart_type": envelope.artifact.chart_type,
                    },
                ),
                AgentOutputItem(
                    type="chart_context_contribution",
                    data=contribution.model_dump(mode="python"),
                    metadata={"artifact_id": envelope.artifact.artifact_id},
                ),
            ),
            metadata=metadata,
            memory_searches=resolved.memory_searches,
            tool_calls=resolved.tool_calls,
        )

    async def _handle_followup(
        self,
        *,
        parsed: _ChartIntentPayload,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ChartOutcome:
        summaries = self._collect_chart_summaries(request=request, context=context)
        if not summaries:
            answer = parsed.answer or "I need a previously generated chart summary before I can answer that follow-up."
            return _ChartOutcome(
                answer=self.normalize_response_text(answer)[0],
                metadata={"response_mode": "chart_followup_missing_summary", "chart_intent": parsed.intent},
            )

        summary = self._select_summary(parsed=parsed, request=request, summaries=summaries)
        if summary is None:
            answer = parsed.answer or "I could not determine which chart you are referring to. Please mention the chart title or artifact ID."
            return _ChartOutcome(
                answer=self.normalize_response_text(answer)[0],
                metadata={"response_mode": "chart_followup_ambiguous", "chart_intent": parsed.intent},
            )

        summary_answer = self._answer_from_summary(parsed=parsed, summary=summary, message=request.message)
        if summary_answer is not None and not parsed.requires_exact_data:
            return _ChartOutcome(
                answer=self.normalize_response_text(summary_answer)[0],
                metadata={
                    "response_mode": "chart_followup_summary",
                    "chart_intent": parsed.intent,
                    "referenced_artifact_id": summary.artifact_id,
                },
            )

        gateway = self._resolve_visualization_gateway(context=context)
        visualization_context = self._build_visualization_context(request=request, context=context)
        exact_answer = await self._answer_from_retrieval(
            parsed=parsed,
            summary=summary,
            gateway=gateway,
            visualization_context=visualization_context,
        )
        return _ChartOutcome(
            answer=self.normalize_response_text(exact_answer)[0],
            metadata={
                "response_mode": "chart_followup_retrieval",
                "chart_intent": parsed.intent,
                "referenced_artifact_id": summary.artifact_id,
            },
        )

    async def _resolve_chart_data(
        self,
        *,
        parsed: _ChartIntentPayload,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ResolvedChartData | None:
        local_rows = self._resolve_local_chart_data(request=request, context=context)
        if local_rows is not None:
            return local_rows

        memory_rows = await self._search_memory_rows(request=request, context=context)
        if memory_rows is not None:
            return memory_rows

        tool_rows = await self._execute_tool_for_rows(parsed=parsed, request=request, context=context)
        return tool_rows

    def _resolve_local_chart_data(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ResolvedChartData | None:
        user_rows = self._extract_inline_rows(request.message)
        if user_rows is not None:
            return _ResolvedChartData(rows=tuple(user_rows), source="user_provided")

        synthesized_rows = self._synthesize_deterministic_rows(request=request)
        if synthesized_rows is not None:
            return synthesized_rows

        workflow_rows = self._extract_workflow_state_rows(context)
        if workflow_rows is not None:
            return _ResolvedChartData(rows=tuple(workflow_rows), source="workflow_state")

        uploaded_rows = self._extract_uploaded_file_rows(request)
        if uploaded_rows is not None:
            return _ResolvedChartData(rows=tuple(uploaded_rows), source="uploaded_file")
        return None

    async def _search_memory_rows(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ResolvedChartData | None:
        require_capability_allowed(self.structured_capabilities, "memory_read", agent_name=self.name)
        await require_capability_policy(
            context,
            request=request,
            capability_name="memory_read",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type},
        )
        scope = MemoryScope(
            user_id=request.user_id,
            project_id=request.project_id,
            session_id=request.session_id,
            usecase=request.usecase,
            agent_name=self.name,
        )
        search_request = MemorySearchRequest(
            text=request.message,
            scope=scope,
            limit=3,
            include_document_chunks=True,
            metadata={"purpose": "visualization"},
        )
        search_result = await context.memory.search(search_request, context)
        for result in search_result.results:
            rows = self._extract_rows_from_memory_result(result)
            if rows is not None:
                return _ResolvedChartData(
                    rows=tuple(rows),
                    source="memory",
                    metadata={"memory_result_id": result.memory_id},
                    memory_searches=1,
                )
        return None

    async def _execute_tool_for_rows(
        self,
        *,
        parsed: _ChartIntentPayload,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ResolvedChartData | None:
        allowed_tools = self._allowed_tool_names(request)
        if not allowed_tools:
            return None

        require_capability_allowed(self.structured_capabilities, "tool_execute", agent_name=self.name)
        await require_capability_policy(
            context,
            request=request,
            capability_name="tool_execute",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type},
        )

        tool_name = parsed.tool_name if parsed.tool_name in allowed_tools else None
        if tool_name is None:
            if len(allowed_tools) != 1:
                return None
            tool_name = allowed_tools[0]

        tool_definition = await context.tools.get_tool(tool_name, context)
        if tool_definition is None or not tool_definition.enabled:
            raise AgentToolIntentError("The requested logical chart data tool is not available.")

        tool_request = ToolExecutionRequest(
            tool_name=tool_name,
            arguments=parsed.tool_arguments or {"query": request.message, "limit": _DEFAULT_MAX_TOOL_ROWS},
            scopes=ToolScopes(
                user_id=request.user_id,
                project_id=request.project_id,
                session_id=request.session_id,
                agent_name=self.name,
                usecase=request.usecase,
            ),
            metadata={"purpose": "visualization"},
        )
        result = await context.tools.execute(tool_request, context)
        if result.status != "completed":
            raise AgentToolIntentError(
                result.summary.safe_message if result.summary is not None and result.summary.safe_message else "The chart data tool did not return a completed result."
            )

        dataset = self._validate_structured_dataset_result(result)
        if dataset.truncated or (
            dataset.total_row_count is not None and dataset.total_row_count > dataset.row_count
        ):
            raise ChartDataMissingError(
                "The approved tool returned a truncated dataset. Please narrow the date range, filters, or aggregation and try again."
            )

        return _ResolvedChartData(
            rows=tuple(dict(row) for row in dataset.rows),
            source="tool",
            metadata={
                "source": dataset.source,
                "tool_name": tool_name,
                "dataset_id": dataset.dataset_id,
            },
            warnings=tuple(dataset.warnings),
            tool_calls=1,
        )

    def _validate_structured_dataset_result(
        self,
        result: ToolExecutionResult,
    ) -> _StructuredDatasetResponse:
        payload = result.structured_content if isinstance(result.structured_content, Mapping) else None
        if payload is None:
            for content_item in result.content:
                if content_item.type == "json" and isinstance(content_item.json_value, Mapping):
                    payload = dict(content_item.json_value)
                    break
                if content_item.type == "text" and content_item.text:
                    parsed = self._try_parse_json_text(content_item.text)
                    if isinstance(parsed, Mapping):
                        payload = dict(parsed)
                        break
        if payload is None:
            raise AgentToolIntentError("The chart data tool did not return a structured dataset payload.")
        try:
            return _StructuredDatasetResponse.model_validate(payload)
        except ValidationError as exc:
            raise AgentToolIntentError("The chart data tool returned an invalid structured dataset.") from exc

    async def _answer_from_retrieval(
        self,
        *,
        parsed: _ChartIntentPayload,
        summary: ChartContextSummary,
        gateway: VisualizationGateway,
        visualization_context: VisualizationContext,
    ) -> str:
        fields = parsed.required_fields or list(summary.y_fields) or ([summary.x_field] if summary.x_field else [])
        try:
            data_slice = await gateway.retrieve_chart_artifact(
                summary.artifact_id,
                visualization_context,
                return_type="data_slice",
                fields=fields,
                filters=parsed.filters,
                max_rows=5,
            )
        except ChartArtifactNotFoundError:
            return "I no longer have access to the underlying chart data. Please regenerate the chart or provide the dataset again."
        if not isinstance(data_slice, ChartDataSlice):
            raise AgentConfigurationError("Visualization follow-up retrieval returned an unexpected payload.")
        if not data_slice.rows:
            return "I could not find matching chart values for that follow-up question."
        row = data_slice.rows[0]
        if len(data_slice.rows) == 1:
            return self._format_single_row_answer(row=row, required_fields=fields, summary=summary)

        preview = "; ".join(json.dumps(item, sort_keys=True) for item in data_slice.rows[:3])
        return f"I found {len(data_slice.rows)} matching rows in {summary.title}: {preview}"

    def _format_single_row_answer(
        self,
        *,
        row: Mapping[str, Any],
        required_fields: Sequence[str],
        summary: ChartContextSummary,
    ) -> str:
        label_field = summary.x_field or summary.series_field or next(iter(row.keys()), None)
        label_value = row.get(label_field) if label_field is not None else None
        metric_fields = [field_name for field_name in required_fields if field_name in row and field_name != label_field]
        if not metric_fields:
            metric_fields = [field_name for field_name in row if field_name != label_field]
        if len(metric_fields) == 1:
            metric_field = metric_fields[0]
            if label_value is not None:
                return f"For {label_value}, {metric_field} was {_format_scalar(row.get(metric_field))}."
            return f"{metric_field} was {_format_scalar(row.get(metric_field))}."

        details = ", ".join(
            f"{field_name}={_format_scalar(row.get(field_name))}"
            for field_name in metric_fields
        )
        if label_value is not None:
            return f"For {label_value}, {details}."
        return details

    def _answer_from_summary(
        self,
        *,
        parsed: _ChartIntentPayload,
        summary: ChartContextSummary,
        message: str,
    ) -> str | None:
        question_type = parsed.question_type
        if question_type in {"summary", "overview", "what_does_this_show"}:
            return summary.summary_text

        if question_type in {"trend", "trend_summary"} and summary.trend_summary:
            if parsed.required_fields:
                trend_lines = [
                    summary.trend_summary.get(field_name)
                    for field_name in parsed.required_fields
                    if isinstance(summary.trend_summary.get(field_name), str)
                ]
                if trend_lines:
                    return " ".join(trend_lines)
            return " ".join(
                f"{field_name}: {description}"
                for field_name, description in summary.trend_summary.items()
                if isinstance(description, str)
            )

        if question_type == "extrema_lookup" and summary.extrema:
            lowered_message = message.casefold()
            preferred_direction = "highest" if "highest" in lowered_message or "max" in lowered_message else "lowest"
            preferred_metric = next(
                (
                    field_name
                    for field_name in parsed.required_fields
                    if any(field_name.casefold() in key.casefold() for key in summary.extrema)
                ),
                None,
            )
            for key, value in summary.extrema.items():
                if not isinstance(value, Mapping):
                    continue
                lowered_key = key.casefold()
                if preferred_direction not in lowered_key:
                    continue
                if preferred_metric is not None and preferred_metric.casefold() not in lowered_key:
                    continue
                label_name, label_value = next(iter(value.items()))
                if label_name == "value":
                    continue
                numeric_value = value.get("value")
                return (
                    f"In {summary.title}, {key.replace('_', ' ')} was {_format_scalar(numeric_value)} "
                    f"for {label_value}."
                )

        if question_type in _SUPPORTED_SUMMARY_QUESTION_TYPES and summary.summary_text:
            return summary.summary_text
        return None

    def _collect_chart_summaries(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[ChartContextSummary, ...]:
        raw_collections: list[object] = []
        if context.state is not None:
            raw_collections.append(context.state.metadata)
        raw_collections.append(context.metadata)
        raw_collections.append(request.metadata)
        return collect_chart_summaries(*raw_collections)

    def _select_prompt_summaries(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[ChartContextSummary, ...]:
        settings = self._visualization_settings(context)
        summaries = self._collect_chart_summaries(request=request, context=context)
        return select_chart_summaries_for_prompt(
            message=request.message,
            summaries=summaries,
            active_usecase=request.usecase,
            settings=settings,
        )

    def _select_summary(
        self,
        *,
        parsed: _ChartIntentPayload,
        request: AgentRunRequest,
        summaries: Sequence[ChartContextSummary],
    ) -> ChartContextSummary | None:
        if parsed.referenced_artifact_id is not None:
            for summary in summaries:
                if summary.artifact_id == parsed.referenced_artifact_id:
                    return summary

        lowered_message = request.message.casefold()
        for summary in reversed(summaries):
            if summary.artifact_id.casefold() in lowered_message:
                return summary
            title = summary.title.casefold()
            if title and title in lowered_message:
                return summary
            if summary.chart_type.replace("_", " ") in lowered_message:
                return summary

        return summaries[-1] if summaries else None

    def _build_chart_request(
        self,
        *,
        parsed: _ChartIntentPayload,
        normalized_chart_type: str,
        resolved: _ResolvedChartData,
        fallback_title: str | None = None,
    ) -> ChartRequest:
        rows = list(resolved.rows)
        inferred_fields = _infer_chart_fields(rows)
        numeric_fields = [
            field_name
            for field_name in inferred_fields.get("y_fields", [])
            if isinstance(field_name, str)
        ]
        row_keys = list(rows[0].keys()) if rows else []
        label_fields = [field_name for field_name in row_keys if field_name not in numeric_fields]
        x_field = parsed.x_field or inferred_fields.get("x_field")
        y_fields = parsed.y_fields or inferred_fields.get("y_fields", [])
        category_field = parsed.category_field or inferred_fields.get("category_field")
        series_field = parsed.series_field
        value_field = parsed.value_field or inferred_fields.get("value_field")
        time_field = parsed.time_field or inferred_fields.get("time_field")
        start_field = parsed.start_field or _infer_named_field(rows, ("start", "start_date", "begin", "begin_date"))
        end_field = parsed.end_field or _infer_named_field(rows, ("end", "end_date", "finish", "finish_date"))
        options: dict[str, Any] = {}

        if parsed.size_field is not None:
            options["size_field"] = parsed.size_field
        if start_field is not None:
            options["start_field"] = start_field
        if end_field is not None:
            options["end_field"] = end_field

        if normalized_chart_type == "gantt":
            if x_field is None:
                x_field = category_field or inferred_fields.get("x_field")
            if x_field is None or start_field is None or end_field is None:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need task, start, and end fields."
                )
            y_fields = []
        elif normalized_chart_type in {"pie", "donut", "treemap"}:
            if category_field is None:
                category_field = x_field or inferred_fields.get("category_field")
            if value_field is None and y_fields:
                value_field = y_fields[0]
            if category_field is None or value_field is None:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need both a category field and a numeric value field."
                )
            y_fields = []
        elif normalized_chart_type == "scatter":
            if x_field is None:
                x_field = _first_distinct_field(numeric_fields)
            scatter_y_field = _first_distinct_field(
                [*list(y_fields), value_field, *numeric_fields],
                exclude=(x_field,),
            )
            if x_field is None or scatter_y_field is None:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need numeric x and y fields."
                )
            y_fields = [scatter_y_field]
            value_field = scatter_y_field
        elif normalized_chart_type == "bubble":
            if x_field is None:
                x_field = _first_distinct_field(numeric_fields)
            bubble_y_field = _first_distinct_field(
                [*list(y_fields), value_field, *numeric_fields],
                exclude=(x_field,),
            )
            size_field = _optional_text(options.get("size_field")) or _first_distinct_field(
                numeric_fields,
                exclude=(x_field, bubble_y_field),
            )
            if size_field is not None:
                options["size_field"] = size_field
            if x_field is None or bubble_y_field is None or size_field is None:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need x, y, and bubble size numeric fields."
                )
            y_fields = [bubble_y_field]
            value_field = bubble_y_field
        elif normalized_chart_type == "histogram":
            histogram_field = x_field or value_field or _first_distinct_field(numeric_fields)
            if histogram_field is None:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need a numeric distribution field."
                )
            x_field = histogram_field
            y_fields = []
            value_field = histogram_field
        elif normalized_chart_type == "heatmap":
            if x_field is None:
                x_field = time_field or inferred_fields.get("x_field") or _first_distinct_field(label_fields)
            if series_field is None:
                series_field = _first_distinct_field(label_fields, exclude=(x_field,))
            if value_field is None:
                value_field = _first_distinct_field(
                    [*list(y_fields), *numeric_fields],
                    exclude=(x_field, series_field),
                )
            if x_field is None or series_field is None or value_field is None:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need x, y, and numeric intensity fields."
                )
            y_fields = [value_field]
        else:
            if x_field is None:
                x_field = category_field or inferred_fields.get("x_field")
            if not y_fields and value_field is not None:
                y_fields = [value_field]
            if x_field is None or not y_fields:
                raise ChartDataMissingError(
                    "I can generate that chart, but I still need one x/category field and at least one numeric y/value field."
                )

        return ChartRequest(
            chart_type=normalized_chart_type,
            title=parsed.title
            or fallback_title
            or f"{normalized_chart_type.replace('_', ' ').title()} chart",
            description=parsed.description,
            x_field=x_field,
            y_fields=list(y_fields),
            category_field=category_field,
            series_field=series_field,
            value_field=value_field,
            time_field=time_field,
            filters=dict(parsed.filters),
            options=options,
            data_source=resolved.source,
        )

    def _resolve_requested_chart_type(
        self,
        *,
        parsed_chart_type: str | None,
        message: str,
        settings: object,
    ) -> str | None:
        explicit_chart_type = self._infer_explicit_chart_type_from_message(message, settings)
        if explicit_chart_type is not None:
            return explicit_chart_type
        return self._normalize_chart_type(parsed_chart_type, settings)

    def _normalize_chart_type(self, chart_type: str | None, settings: object) -> str | None:
        raw = _optional_text(chart_type)
        if raw is None:
            return None
        aliases = getattr(settings, "aliases", {})
        if isinstance(aliases, Mapping):
            alias_match = aliases.get(raw.casefold())
            if isinstance(alias_match, str):
                return alias_match

        normalized = raw.casefold().replace("-", "_").replace(" ", "_")
        simplified = normalized
        for suffix in ("_chart", "_graph", "_plot"):
            if normalized in getattr(settings, "allowed_chart_types", ()):  # preserve canonical names like box_plot
                return normalized
            if simplified.endswith(suffix):
                simplified = simplified[: -len(suffix)]
                break

        if simplified in getattr(settings, "allowed_chart_types", ()):
            return simplified
        for key, value in getattr(settings, "aliases", {}).items():
            normalized_key = key.casefold().replace("-", "_").replace(" ", "_")
            if normalized_key == normalized:
                return value
        return simplified

    def _resolve_visualization_gateway(self, *, context: OrchestrationContext) -> VisualizationGateway:
        existing = context.metadata.get("visualization_gateway")
        if existing is not None:
            return existing  # type: ignore[return-value]
        try:
            return build_visualization_gateway(
                context.config,
                policy_service=context.policy,
                trace_recorder=context.observability,
            )
        except Exception as exc:  # pragma: no cover - configuration failure path
            raise AgentConfigurationError("Visualization is not configured for chart generation.") from exc

    def _visualization_settings(self, context: OrchestrationContext):
        try:
            return get_visualization_settings(context.config)
        except Exception as exc:  # pragma: no cover - configuration failure path
            raise AgentConfigurationError("Visualization settings are not available.") from exc

    def _build_visualization_context(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> VisualizationContext:
        policy_scope = sanitize_metadata(
            {
                "project_id": request.project_id,
                "tenant_id": context.runtime_metadata.get("tenant_id"),
            }
        )
        return VisualizationContext(
            user_id=request.user_id or "anonymous",
            session_id=request.session_id,
            usecase=request.usecase,
            agent_name=self.name,
            trace_id=request.trace_id,
            policy_scope=policy_scope,
            config={},
        )

    async def _record_chart_resolution_event(
        self,
        *,
        context: OrchestrationContext,
        request: AgentRunRequest,
        event_name: str,
        payload: Mapping[str, Any],
        status: str = "completed",
    ) -> None:
        recorder = context.observability
        if recorder is None:
            return
        await recorder.record(
            event_type="agent",
            component=self.component,
            event_name=event_name,
            status=status,
            trace_id=request.trace_id,
            session_id=request.session_id,
            user_id=request.user_id,
            usecase=request.usecase,
            agent_name=self.name,
            strategy_name=request.strategy_name,
            llm_profile=request.llm_profile,
            payload=sanitize_metadata(payload),
        )

    def _allowed_tool_names(self, request: AgentRunRequest) -> tuple[str, ...]:
        request_tools = _normalize_text_list(request.available_tools)
        configured_tools = _normalize_text_list(getattr(self, "allowed_tool_intents", ()))
        if request_tools and configured_tools:
            intersection = [tool_name for tool_name in request_tools if tool_name in configured_tools]
            if intersection:
                return tuple(intersection)
        if request_tools:
            return tuple(request_tools)
        return tuple(configured_tools)

    def _build_native_tool_definitions(
        self,
        allowed_tools: Sequence[str],
        *,
        context: OrchestrationContext,
    ) -> list[LLMToolDefinition]:
        tool_sections = self._configured_tool_sections(context)
        definitions: list[LLMToolDefinition] = []
        for tool_name in allowed_tools:
            tool_section = tool_sections.get(tool_name)
            description = None
            parameters: dict[str, Any] | None = None
            if isinstance(tool_section, Mapping):
                description = _optional_text(tool_section.get("description"))
                raw_parameters = tool_section.get("input_schema_override")
                if isinstance(raw_parameters, Mapping):
                    parameters = dict(raw_parameters)
            if parameters is None:
                parameters = {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                }
            definitions.append(
                LLMToolDefinition(
                    function=LLMToolFunction(
                        name=tool_name,
                        description=description,
                        parameters=parameters,
                    )
                )
            )
        return definitions

    def _build_native_tool_payload(
        self,
        tool_calls: Sequence[LLMToolCall],
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> _ChartIntentPayload:
        if len(tool_calls) != 1:
            raise AgentToolIntentError("Chart agent can call at most one logical chart data tool per turn.")

        tool_call = tool_calls[0]
        function = tool_call.function
        if not isinstance(function, LLMToolCallFunction):
            function = LLMToolCallFunction.from_mapping(function)

        tool_name = _optional_text(function.name)
        allowed_tools = self._allowed_tool_names(request)
        if tool_name is None or tool_name not in allowed_tools:
            raise AgentToolIntentError("Chart agent selected a tool outside the allowed logical tool set.")

        arguments: dict[str, Any] = {}
        raw_arguments = function.arguments.strip()
        if raw_arguments:
            try:
                parsed_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise AgentOutputParseError(
                    "Chart agent returned tool-call arguments that were not valid JSON."
                ) from exc
            if not isinstance(parsed_arguments, Mapping):
                raise AgentOutputParseError(
                    "Chart agent tool-call arguments must decode to a JSON object."
                )
            arguments = sanitize_metadata(dict(parsed_arguments))

        settings = self._visualization_settings(context)
        chart_type = self._infer_chart_type_from_message(request.message, settings)
        if chart_type is None:
            raise AgentToolIntentError(
                "Chart agent requested a native tool call but did not provide or imply a supported chart type."
            )

        return _ChartIntentPayload.model_validate(
            {
                "intent": "generate_chart",
                "chart_type": chart_type,
                "requires_data": True,
                "data_source_hint": "tool",
                "tool_name": tool_name,
                "tool_arguments": arguments,
                "answer": f"Here is the {chart_type.replace('_', ' ')} chart.",
            }
        )

    def _configured_tool_sections(self, context: OrchestrationContext) -> Mapping[str, Any]:
        try:
            tool_sections = context.config.section("tooling.registry.tools")
        except Exception:
            return {}
        return tool_sections if isinstance(tool_sections, Mapping) else {}

    def _infer_explicit_chart_type_from_message(self, message: str, settings: object) -> str | None:
        lowered_message = message.casefold()
        allowed_types = tuple(getattr(settings, "allowed_chart_types", ()))
        for chart_type in sorted(allowed_types, key=len, reverse=True):
            if chart_type.casefold() in lowered_message:
                return chart_type
            if chart_type.replace("_", " ") in lowered_message:
                return chart_type

        aliases = getattr(settings, "aliases", {})
        if isinstance(aliases, Mapping):
            for alias, canonical in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
                if not isinstance(alias, str) or not isinstance(canonical, str):
                    continue
                if alias.casefold() in lowered_message:
                    return canonical
        return None

    def _infer_chart_type_from_message(self, message: str, settings: object) -> str | None:
        explicit_chart_type = self._infer_explicit_chart_type_from_message(message, settings)
        if explicit_chart_type is not None:
            return explicit_chart_type

        lowered_message = message.casefold()
        allowed_types = tuple(getattr(settings, "allowed_chart_types", ()))
        if any(
            phrase in lowered_message
            for phrase in (
                "price",
                "prices",
                "trend",
                "over time",
                "time series",
                "timeseries",
                "projection",
                "forecast",
                "growth rate",
                "investment",
            )
        ) and "line" in allowed_types:
            return "line"
        return None

    def _render_summary_for_prompt(self, summary: ChartContextSummary) -> str:
        lines = [
            f"artifact_id: {summary.artifact_id}",
            f"title: {summary.title}",
            f"chart_type: {summary.chart_type}",
            f"summary: {truncate_text(summary.summary_text, max_chars=400) or summary.summary_text}",
        ]
        if summary.key_insights:
            lines.append("key_insights: " + "; ".join(summary.key_insights[:3]))
        if summary.data_ref is not None:
            lines.append(f"data_ref: {summary.data_ref}")
        return "\n".join(lines)

    def _missing_data_answer(self, parsed: _ChartIntentPayload) -> str:
        if parsed.missing_information:
            return (
                "I can generate that chart, but I still need "
                + ", ".join(parsed.missing_information)
                + "."
            )
        return "I can generate that chart, but I still need the underlying structured data values first."

    def _extract_inline_rows(self, message: str) -> list[dict[str, Any]] | None:
        for block in _INLINE_JSON_BLOCK_RE.findall(message):
            rows = _rows_from_any_payload(self._try_parse_json_text(block))
            if rows is not None:
                return rows

        parsed = self._try_parse_json_text(message)
        rows = _rows_from_any_payload(parsed)
        if rows is not None:
            return rows

        for payload in _iter_embedded_json_payloads(message):
            rows = _rows_from_any_payload(payload)
            if rows is not None:
                return rows

        return _parse_markdown_table(message)

    def _extract_workflow_state_rows(self, context: OrchestrationContext) -> list[dict[str, Any]] | None:
        state = context.state
        if state is None:
            return None
        rows = _rows_from_any_payload(state.metadata.get("chart_data"))
        if rows is not None:
            return rows
        rows = _rows_from_any_payload(state.metadata.get("visualization_data"))
        if rows is not None:
            return rows
        for message in reversed(state.messages):
            rows = self._extract_inline_rows(message.content)
            if rows is not None:
                return rows
        return None

    def _extract_uploaded_file_rows(self, request: AgentRunRequest) -> list[dict[str, Any]] | None:
        for section in list(request.context_items) + list(request.tool_context):
            source = _optional_text(section.metadata.get("source")) if isinstance(section.metadata, Mapping) else None
            title = section.title.casefold()
            if source != "uploaded_file" and "upload" not in title and "file" not in title:
                continue
            rows = self._extract_inline_rows(section.body)
            if rows is not None:
                return rows
        return None

    def _synthesize_deterministic_rows(
        self,
        *,
        request: AgentRunRequest,
    ) -> _ResolvedChartData | None:
        projection = _parse_compound_growth_projection(request.message)
        if projection is not None:
            rows = _build_compound_growth_rows(projection)
            warnings = (projection.warning,) if projection.warning is not None else ()
            return _ResolvedChartData(
                rows=tuple(rows),
                source="deterministic_synthesis",
                metadata={
                    "synthesis_kind": "compound_growth_projection",
                    "initial_amount": round(projection.initial_amount, 2),
                    "annual_growth_rate_pct": projection.annual_growth_rate_pct,
                    "horizon_count": projection.horizon_count,
                    "horizon_unit": projection.horizon_unit,
                    "asset_label": projection.asset_label,
                },
                warnings=warnings,
            )

        percentage_rows = _build_percentage_split_rows(request.message)
        if percentage_rows is not None:
            return _ResolvedChartData(
                rows=tuple(percentage_rows),
                source="deterministic_synthesis",
                metadata={
                    "synthesis_kind": "percentage_split",
                    "slice_count": len(percentage_rows),
                },
            )

        return None

    def _extract_rows_from_memory_result(self, result: MemoryResult) -> list[dict[str, Any]] | None:
        record_metadata = getattr(result.record, "metadata", None)
        if isinstance(record_metadata, Mapping):
            rows = _rows_from_any_payload(record_metadata)
            if rows is not None:
                return rows
        if isinstance(result.record, Mapping):
            rows = _rows_from_any_payload(result.record.get("metadata"))
            if rows is not None:
                return rows
        metadata_rows = _rows_from_any_payload(result.metadata)
        if metadata_rows is not None:
            return metadata_rows
        return self._extract_inline_rows(result.text)

    def _try_parse_json_text(self, text: str) -> object | None:
        normalized = text.strip()
        if not normalized:
            return None
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            return None


def _iter_embedded_json_payloads(text: str) -> list[object]:
    decoder = json.JSONDecoder()
    payloads: list[object] = []
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        payloads.append(payload)
    return payloads


def _rows_from_any_payload(payload: object) -> list[dict[str, Any]] | None:
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes | bytearray):
        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, Mapping):
                return None
            rows.append(dict(item))
        return rows or None

    if isinstance(payload, Mapping):
        for key in ("rows", "data", "values", "items"):
            if key in payload:
                rows = _rows_from_any_payload(payload.get(key))
                if rows is not None:
                    return rows
        for value in payload.values():
            rows = _rows_from_any_payload(value)
            if rows is not None:
                return rows
    return None


def _parse_markdown_table(text: str) -> list[dict[str, Any]] | None:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) < 3:
        return None
    for start_index in range(len(lines) - 2):
        headers = _split_markdown_row(lines[start_index])
        separator = _split_markdown_row(lines[start_index + 1])
        if not headers or not separator or len(headers) != len(separator):
            continue
        if not all(_MARKDOWN_SEPARATOR_RE.fullmatch(item) for item in separator):
            continue

        rows: list[dict[str, Any]] = []
        for row_line in lines[start_index + 2 :]:
            values = _split_markdown_row(row_line)
            if len(values) != len(headers):
                break
            rows.append(
                {
                    header: _coerce_table_scalar(value)
                    for header, value in zip(headers, values, strict=True)
                }
            )
        if rows:
            return rows
    return None


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    if not stripped:
        return []
    return [part.strip() for part in stripped.split("|")]


def _infer_chart_title_from_message(message: str) -> str | None:
    match = _PROMPT_TITLE_RE.search(message)
    if match is None:
        return None
    return _optional_text(match.group("title"))


def _coerce_table_scalar(value: str) -> Any:
    normalized = value.strip()
    lowered = normalized.casefold()
    if lowered in {"", "null", "none", "n/a"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    numeric_candidate = normalized
    negative = False
    if numeric_candidate.startswith("(") and numeric_candidate.endswith(")"):
        negative = True
        numeric_candidate = numeric_candidate[1:-1].strip()
    if numeric_candidate.startswith(_TABLE_CURRENCY_SYMBOLS):
        numeric_candidate = numeric_candidate[1:].strip()

    sign = ""
    if numeric_candidate.startswith(("+", "-")):
        sign = numeric_candidate[0]
        numeric_candidate = numeric_candidate[1:].strip()
    if numeric_candidate.startswith(_TABLE_CURRENCY_SYMBOLS):
        numeric_candidate = numeric_candidate[1:].strip()

    numeric_candidate = numeric_candidate.replace(",", "")
    try:
        if negative and sign != "-":
            sign = "-"
        if sign:
            numeric_candidate = f"{sign}{numeric_candidate}"
        if "." in numeric_candidate:
            return float(numeric_candidate)
        return int(numeric_candidate)
    except ValueError:
        return normalized


def _parse_compound_growth_projection(message: str) -> _CompoundGrowthProjection | None:
    lowered_message = message.casefold()
    if not any(token in lowered_message for token in _COMPOUND_GROWTH_HINTS):
        return None

    amount_match = _COMPOUND_GROWTH_AMOUNT_RE.search(message)
    rate_match = _COMPOUND_GROWTH_RATE_RE.search(message)
    horizon_match = _COMPOUND_GROWTH_HORIZON_RE.search(message)
    if amount_match is None or rate_match is None or horizon_match is None:
        return None

    initial_amount = _parse_compound_growth_number(amount_match.group("amount"))
    annual_growth_rate_pct = _parse_compound_growth_number(rate_match.group("rate"))
    horizon_count = int(horizon_match.group("count"))
    if initial_amount is None or annual_growth_rate_pct is None or horizon_count <= 0:
        return None
    if annual_growth_rate_pct <= -100:
        return None

    raw_unit = horizon_match.group("unit").casefold()
    horizon_unit: Literal["month", "year"] = "month" if raw_unit.startswith(("mo", "month")) else "year"
    max_horizon = _MAX_COMPOUND_GROWTH_MONTHS if horizon_unit == "month" else _MAX_COMPOUND_GROWTH_YEARS
    warning: str | None = None
    if horizon_count > max_horizon:
        warning = (
            f"Projection horizon was capped at {max_horizon} {horizon_unit}s to keep the dataset bounded."
        )
        horizon_count = max_horizon

    asset_match = _COMPOUND_GROWTH_ASSET_RE.search(message)
    asset_label = asset_match.group("asset") if asset_match is not None else None
    return _CompoundGrowthProjection(
        initial_amount=initial_amount,
        annual_growth_rate_pct=annual_growth_rate_pct,
        horizon_count=horizon_count,
        horizon_unit=horizon_unit,
        asset_label=asset_label,
        warning=warning,
    )


def _parse_compound_growth_number(text: str) -> float | None:
    normalized = text.replace(",", "").strip()
    try:
        return float(normalized)
    except ValueError:
        return None


def _normalize_percentage_split_value(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return round(value, 4)


def _clean_percentage_split_label(value: str) -> str:
    return value.strip().strip("'\"").strip()


def _build_percentage_split_rows(message: str) -> list[dict[str, Any]] | None:
    lowered_message = message.casefold()
    if "pie" not in lowered_message and "donut" not in lowered_message:
        return None

    match = _PERCENTAGE_SPLIT_RE.search(message)
    if match is None:
        return None

    first_value = _parse_compound_growth_number(match.group("first_value"))
    if first_value is None or first_value < 0 or first_value > 100:
        return None

    second_value = round(100 - first_value, 4)
    if second_value < 0:
        return None

    first_label = _clean_percentage_split_label(match.group("first_label"))
    second_label = _clean_percentage_split_label(match.group("second_label"))
    if not first_label or not second_label:
        return None

    return [
        {"label": first_label, "value": _normalize_percentage_split_value(first_value)},
        {"label": second_label, "value": _normalize_percentage_split_value(second_value)},
    ]


def _build_compound_growth_rows(projection: _CompoundGrowthProjection) -> list[dict[str, Any]]:
    base_date = date.today()
    periods_per_year = 12 if projection.horizon_unit == "month" else 1
    period_rate = projection.annual_growth_rate_pct / 100.0 / periods_per_year

    rows: list[dict[str, Any]] = []
    for offset in range(projection.horizon_count + 1):
        point_date = _shift_projection_date(base_date, offset=offset, unit=projection.horizon_unit)
        projected_value = round(projection.initial_amount * ((1 + period_rate) ** offset), 2)
        rows.append(
            {
                "date": point_date.isoformat(),
                "projected_value": projected_value,
            }
        )
    return rows


def _shift_projection_date(base_date: date, *, offset: int, unit: Literal["month", "year"]) -> date:
    if unit == "year":
        return _replace_year(base_date, base_date.year + offset)
    return _add_months(base_date, offset)


def _replace_year(base_date: date, year: int) -> date:
    day = min(base_date.day, monthrange(year, base_date.month)[1])
    return date(year, base_date.month, day)


def _add_months(base_date: date, months: int) -> date:
    total_months = (base_date.year * 12 + (base_date.month - 1)) + months
    year = total_months // 12
    month = total_months % 12 + 1
    day = min(base_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def _value_matches_dataset_type(value: Any, data_type: str) -> bool:
    if data_type == "string":
        return isinstance(value, str)
    if data_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type in {"date", "datetime"}:
        return isinstance(value, str)
    return False


def _infer_chart_fields(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"y_fields": []}
    keys = list(rows[0].keys())
    numeric_fields = [
        key
        for key in keys
        if all(
            value is None or isinstance(value, int | float) and not isinstance(value, bool)
            for value in (row.get(key) for row in rows)
        )
    ]
    temporal_fields = [
        key
        for key in keys
        if all(value is None or _looks_like_date_text(value) for value in (row.get(key) for row in rows))
    ]
    label_fields = [key for key in keys if key not in numeric_fields]
    x_field = temporal_fields[0] if temporal_fields else (label_fields[0] if label_fields else None)
    category_field = label_fields[0] if label_fields else x_field
    value_field = numeric_fields[0] if numeric_fields else None
    return {
        "x_field": x_field,
        "y_fields": numeric_fields,
        "category_field": category_field,
        "value_field": value_field,
        "time_field": temporal_fields[0] if temporal_fields else None,
    }


def _infer_named_field(rows: Sequence[Mapping[str, Any]], candidates: Sequence[str]) -> str | None:
    if not rows:
        return None
    first_row = rows[0]
    normalized_to_actual = {
        str(key).casefold().replace("-", "_").replace(" ", "_"): str(key)
        for key in first_row.keys()
    }
    for candidate in candidates:
        actual = normalized_to_actual.get(candidate.casefold().replace("-", "_").replace(" ", "_"))
        if actual is not None:
            return actual
    return None


def _first_distinct_field(fields: Sequence[object], exclude: Sequence[object] = ()) -> str | None:
    excluded = {
        normalized
        for normalized in (_optional_text(value) for value in exclude)
        if normalized is not None
    }
    for value in fields:
        normalized = _optional_text(value)
        if normalized is None or normalized in excluded:
            continue
        return normalized
    return None


def _looks_like_date_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized:
        return False
    for parser in (date.fromisoformat, datetime.fromisoformat):
        try:
            parser(normalized)
            return True
        except ValueError:
            continue
    return bool(re.fullmatch(r"\d{4}[-/]\d{2}([-/]\d{2})?", normalized))


def _format_scalar(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if value is None:
        return "null"
    return str(value)


__all__ = ["ChartAgent"]