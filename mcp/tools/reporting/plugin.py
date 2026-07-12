"""FastMCP plugin registration for the reporting tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.tools_base.dataset_models import MetricAggregation, MetricGranularity, MetricSeriesQuery, SortOrder
from app.tools_base.dataset_validation import DatasetTransportLimits, normalize_structured_dataset_result
from app.tools_base.decorators import guard_tool_call, observe_tool_call
from app.tools_base.models import CapabilityDescriptor, ToolHealth
from app.tools_base.plugin import ToolPlugin

from tools.reporting.models import ReportingToolConfig, load_reporting_tool_config
from tools.reporting.providers import ReportingProviderError, ReportingValidationError
from tools.reporting.service import ReportingRuntimeService, ReportingService


TOOL_NAME = "reporting.query_metric_series"
CAPABILITY_NAME = "reporting.metric_series.read"


@dataclass(slots=True)
class ReportingPlugin:
    """Plugin that exposes bounded reporting datasets for visualization."""

    context: ToolRuntimeContext
    service: ReportingRuntimeService | None = None
    name: str = "reporting"
    version: str = "1.0.0"
    capabilities: list[CapabilityDescriptor] = field(
        default_factory=lambda: [
            CapabilityDescriptor(
                name=CAPABILITY_NAME,
                type="tool",
                description="Query approved aggregated metric series.",
                risk_level="read_only",
            )
        ]
    )
    config: ReportingToolConfig = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.config = load_reporting_tool_config(self.context.tool_config)
        if self.service is None:
            self.service = ReportingService(self.context, config=self.config)

    def register(self, mcp: FastMCP) -> None:
        service = self.service
        assert service is not None
        limits = DatasetTransportLimits(
            max_result_bytes=self.config.max_result_bytes
        )

        @mcp.tool(
            name=TOOL_NAME,
            description="Return bounded structured metric series for approved reporting use cases.",
        )
        @observe_tool_call(
            self.context,
            TOOL_NAME,
            capability_name=CAPABILITY_NAME,
            timeout_seconds=self.config.timeout_seconds,
        )
        @guard_tool_call(self.context, TOOL_NAME)
        async def query_metric_series(
            metric_names: list[str],
            dimension: str,
            start_date: date | None = None,
            end_date: date | None = None,
            filters: dict[str, str | int | float | bool | None] | None = None,
            aggregation: MetricAggregation = "sum",
            granularity: MetricGranularity = "month",
            sort: SortOrder = "asc",
            limit: int | None = None,
        ) -> dict[str, object]:
            request = MetricSeriesQuery(
                metric_names=metric_names,
                dimension=dimension,
                start_date=start_date,
                end_date=end_date,
                filters=filters or {},
                aggregation=aggregation,
                granularity=granularity,
                sort=sort,
                limit=self.config.maximum_rows if limit is None else limit,
            )
            try:
                dataset = await service.query_metric_series(request)
                envelope = normalize_structured_dataset_result(
                    tool_name=TOOL_NAME,
                    dataset=dataset,
                    limits=limits,
                )
            except (ReportingValidationError, ReportingProviderError) as error:
                return error.to_result_envelope(tool_name=TOOL_NAME).model_dump(mode="python")
            except ValueError as error:
                normalized_error = ReportingProviderError.from_dataset_contract_error(error)
                return normalized_error.to_result_envelope(tool_name=TOOL_NAME).model_dump(
                    mode="python"
                )

            return envelope.model_dump(mode="python")

    async def health(self) -> ToolHealth:
        service = self.service
        assert service is not None
        details = service.health_payload()
        state = str(details.get("status") or "ok")
        if state not in {"ok", "degraded", "error"}:
            state = "ok"
        return ToolHealth(state=state, details=details)


def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    return ReportingPlugin(context)
