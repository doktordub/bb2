"""Versioned visualization models for backend chart artifacts and summaries."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SupportedChartType = Literal[
    "bar",
    "grouped_bar",
    "stacked_bar",
    "horizontal_bar",
    "line",
    "multi_line",
    "area",
    "pie",
    "donut",
    "scatter",
    "bubble",
    "histogram",
    "box_plot",
    "heatmap",
    "treemap",
    "waterfall",
    "gantt",
    "radar",
    "table",
]
ChartRenderer = Literal["echarts"]
ChartDataMode = Literal["inline", "reference"]
ChartDataSource = Literal[
    "deterministic_synthesis",
    "user_provided",
    "workflow_state",
    "memory",
    "tool",
    "uploaded_file",
    "unknown",
]
ContextContributionKind = Literal["chart_summary", "tool_summary", "memory_summary"]

CANONICAL_CHART_TYPES = tuple(str(value) for value in get_args(SupportedChartType))
SUPPORTED_CHART_RENDERERS = tuple(str(value) for value in get_args(ChartRenderer))
SUPPORTED_CHART_DATA_MODES = tuple(str(value) for value in get_args(ChartDataMode))
SUPPORTED_CHART_DATA_SOURCES = tuple(str(value) for value in get_args(ChartDataSource))
SUPPORTED_CONTEXT_CONTRIBUTION_KINDS = tuple(
    str(value) for value in get_args(ContextContributionKind)
)


class VisualizationModel(BaseModel):
    """Strict visualization base model with deterministic serialization semantics."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VisualizationContext(VisualizationModel):
    """Context supplied to the visualization boundary during chart generation."""

    user_id: str
    session_id: str
    usecase: str | None = None
    agent_name: str
    trace_id: str | None = None
    policy_scope: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)

    _validate_required_fields = field_validator("user_id", "session_id", "agent_name")(
        lambda cls, value: _required_text(value)
    )
    _validate_optional_fields = field_validator("usecase", "trace_id")(
        lambda cls, value: _optional_text(value)
    )


class ChartRequest(VisualizationModel):
    """Normalized chart-generation request after intent parsing and alias resolution."""

    chart_type: SupportedChartType
    title: str
    description: str | None = None
    x_field: str | None = None
    y_fields: list[str] = Field(default_factory=list)
    category_field: str | None = None
    series_field: str | None = None
    value_field: str | None = None
    time_field: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    data_source: ChartDataSource = "unknown"

    _validate_title = field_validator("title")(lambda cls, value: _required_text(value))
    _validate_optional_fields = field_validator(
        "description",
        "x_field",
        "category_field",
        "series_field",
        "value_field",
        "time_field",
    )(lambda cls, value: _optional_text(value))
    _validate_y_fields = field_validator("y_fields")(lambda cls, value: _normalize_text_list(value))


class ChartArtifact(VisualizationModel):
    """Frontend-facing chart artifact contract."""

    artifact_id: str
    type: Literal["chart"] = "chart"
    chart_type: SupportedChartType
    title: str
    description: str | None = None
    renderer: ChartRenderer
    spec_version: str
    data_mode: ChartDataMode
    data: list[dict[str, Any]] | None = None
    data_ref: str | None = None
    encoding: dict[str, Any]
    options: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_required_text = field_validator("artifact_id", "title", "spec_version")(
        lambda cls, value: _required_text(value)
    )
    _validate_optional_text = field_validator("description", "data_ref")(
        lambda cls, value: _optional_text(value)
    )
    _validate_warning_values = field_validator("warnings")(
        lambda cls, value: _normalize_text_list(value)
    )

    @model_validator(mode="after")
    def validate_data_mode(self) -> "ChartArtifact":
        if self.data_mode == "inline" and self.data is None:
            raise ValueError("inline data_mode requires data")
        if self.data_mode == "reference" and self.data_ref is None:
            raise ValueError("reference data_mode requires data_ref")
        return self


class ChartContextSummary(VisualizationModel):
    """Context-window-safe summary of a generated chart."""

    artifact_id: str
    chart_type: SupportedChartType
    title: str
    description: str | None = None
    renderer: ChartRenderer
    data_source: ChartDataSource
    x_field: str | None = None
    y_fields: list[str] = Field(default_factory=list)
    series_field: str | None = None
    row_count: int = Field(ge=0)
    series_count: int = Field(ge=0)
    category_count: int | None = Field(default=None, ge=0)
    time_range: dict[str, Any] | None = None
    summary_text: str
    key_insights: list[str] = Field(default_factory=list)
    aggregate_stats: dict[str, Any] = Field(default_factory=dict)
    extrema: dict[str, Any] = Field(default_factory=dict)
    trend_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    data_ref: str | None = None
    token_estimate: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_required_text = field_validator("artifact_id", "title", "summary_text")(
        lambda cls, value: _required_text(value)
    )
    _validate_optional_text = field_validator("description", "x_field", "series_field", "data_ref")(
        lambda cls, value: _optional_text(value)
    )
    _validate_y_fields = field_validator("y_fields")(lambda cls, value: _normalize_text_list(value))
    _validate_key_insights = field_validator("key_insights", "warnings")(
        lambda cls, value: _normalize_text_list(value)
    )


class ChartArtifactEnvelope(VisualizationModel):
    """Combined frontend artifact and prompt-safe summary returned by the gateway."""

    artifact: ChartArtifact
    context_summary: ChartContextSummary


class ContextContribution(VisualizationModel):
    """Prompt-context contribution that keeps large artifacts out of chat history."""

    contribution_id: str
    kind: ContextContributionKind
    content: dict[str, Any]
    token_estimate: int = Field(ge=0)
    source_artifact_id: str | None = None
    include_in_next_prompt: bool = True

    _validate_required_text = field_validator("contribution_id")(
        lambda cls, value: _required_text(value)
    )
    _validate_optional_text = field_validator("source_artifact_id")(
        lambda cls, value: _optional_text(value)
    )


class ChartDataSlice(VisualizationModel):
    """Bounded row slice returned for deterministic follow-up retrieval."""

    artifact_id: str
    chart_type: SupportedChartType
    data_ref: str | None = None
    fields: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_required_text = field_validator("artifact_id")(
        lambda cls, value: _required_text(value)
    )
    _validate_optional_text = field_validator("data_ref")(
        lambda cls, value: _optional_text(value)
    )
    _validate_fields = field_validator("fields")(
        lambda cls, value: _normalize_text_list(value)
    )


class ChartComputedFacts(VisualizationModel):
    """Deterministic computed facts returned for exact chart follow-up answers."""

    artifact_id: str
    chart_type: SupportedChartType
    summary_text: str | None = None
    aggregate_stats: dict[str, Any] = Field(default_factory=dict)
    extrema: dict[str, Any] = Field(default_factory=dict)
    trend_summary: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    data_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_required_text = field_validator("artifact_id")(
        lambda cls, value: _required_text(value)
    )
    _validate_optional_text = field_validator("summary_text", "data_ref")(
        lambda cls, value: _optional_text(value)
    )


def _default_supported_data_modes() -> list[ChartDataMode]:
    return ["inline"]


class RendererCapabilities(VisualizationModel):
    """Renderer capability declaration exposed by the visualization boundary."""

    renderer: ChartRenderer
    supported_spec_versions: list[str] = Field(default_factory=lambda: ["1.0"])
    supported_chart_types: list[SupportedChartType] = Field(default_factory=list)
    supported_data_modes: list[ChartDataMode] = Field(default_factory=_default_supported_data_modes)
    supports_reference_data: bool = False
    max_series: int | None = Field(default=None, ge=1)
    max_categories: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_spec_versions = field_validator("supported_spec_versions")(
        lambda cls, value: _normalize_text_list(value)
    )
    _validate_supported_chart_types = field_validator("supported_chart_types")(
        lambda cls, value: _normalize_text_list(value)
    )
    _validate_supported_data_modes = field_validator("supported_data_modes")(
        lambda cls, value: _normalize_text_list(value)
    )

    @model_validator(mode="after")
    def validate_supported_modes(self) -> "RendererCapabilities":
        if not self.supported_chart_types:
            raise ValueError("supported_chart_types must not be empty")
        supports_reference_mode = "reference" in self.supported_data_modes
        if self.supports_reference_data and not supports_reference_mode:
            raise ValueError(
                "supports_reference_data requires reference in supported_data_modes"
            )
        if not self.supports_reference_data and supports_reference_mode:
            raise ValueError(
                "supported_data_modes cannot include reference when supports_reference_data is false"
            )
        return self


def _required_text(value: str) -> str:
    normalized = value.strip()
    if normalized == "":
        raise ValueError("value must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_text_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _required_text(value)
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized