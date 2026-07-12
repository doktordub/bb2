"""Visualization-safe trace and metric helpers for gateway lifecycle events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts.trace import (
    CHART_ARTIFACT_CREATED,
    CHART_ARTIFACT_DELIVERED,
    CHART_ARTIFACT_STORED,
    CHART_CONTEXT_SUMMARY_CREATED,
    CHART_FOLLOWUP_ARTIFACT_RETRIEVED,
    CHART_FOLLOWUP_COMPUTATION_COMPLETED,
    CHART_POLICY_DENIED,
    CHART_REQUEST_DETECTED,
    CHART_REQUEST_FAILED,
    CHART_VALIDATION_FAILED,
    CHART_VALIDATION_STARTED,
    CHART_ARTIFACT_BUILD_STARTED,
)
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder
from app.observability.tracing import TraceRecorder
from app.visualization.errors import ChartPolicyDeniedError
from app.visualization.models import ChartArtifact, ChartContextSummary, VisualizationContext


@dataclass(slots=True)
class VisualizationGatewayObserver:
    """Record safe trace and metrics for visualization gateway operations."""

    trace_recorder: TraceRecorder | None = None
    metrics: MetricsRecorder = field(default_factory=NoopMetricsRecorder)
    component: str = "app.visualization.gateway"

    async def record(
        self,
        *,
        event_name: str,
        context: VisualizationContext,
        chart_type: str | None = None,
        renderer: str | None = None,
        data_source: str | None = None,
        data_mode: str | None = None,
        artifact_id: str | None = None,
        row_count: int | None = None,
        series_count: int | None = None,
        category_count: int | None = None,
        token_estimate: int | None = None,
        return_type: str | None = None,
        status: str = "completed",
        duration_ms: int | None = None,
        error: BaseException | None = None,
    ) -> None:
        policy_block_summary = _policy_block_summary(error)
        payload = {
            "chart_type": chart_type,
            "renderer": renderer,
            "data_source": data_source,
            "artifact_id": artifact_id,
            "data_mode": data_mode,
            "row_count": row_count,
            "series_count": series_count,
            "category_count": category_count,
            "context_summary_token_estimate": token_estimate,
            "return_type": return_type,
            "policy_decision": "deny" if event_name == CHART_POLICY_DENIED else "allow",
            "policy_block_summary": policy_block_summary,
        }
        sanitized_payload = {
            key: value for key, value in payload.items() if value is not None
        }

        if self.trace_recorder is not None:
            await self.trace_recorder.record(
                event_type="visualization",
                event_name=event_name,
                component=self.component,
                trace_id=context.trace_id,
                session_id=context.session_id,
                user_id=context.user_id,
                usecase=context.usecase,
                agent_name=context.agent_name,
                status=status,
                severity="error" if error is not None else "info",
                duration_ms=float(duration_ms) if duration_ms is not None else None,
                error_type=type(error).__name__ if error is not None else None,
                payload=sanitized_payload,
            )

        tags = {
            "component": "visualization",
            "operation": _metric_operation(event_name),
            "chart_type": chart_type,
            "renderer": renderer,
            "data_source": data_source,
            "data_mode": data_mode,
            "event_name": event_name,
            "error_type": type(error).__name__ if error is not None else None,
            "success": "false" if error is not None or status == "failed" else "true",
        }
        self.metrics.increment(_counter_name(event_name), tags=tags)
        if row_count is not None and event_name in {CHART_ARTIFACT_CREATED, CHART_ARTIFACT_DELIVERED}:
            self.metrics.increment("backend.visualization.rows_processed.total", value=row_count, tags=tags)
        if token_estimate is not None and event_name == CHART_CONTEXT_SUMMARY_CREATED:
            self.metrics.increment(
                "backend.visualization.summary_tokens.total",
                value=token_estimate,
                tags=tags,
            )
        if duration_ms is not None:
            self.metrics.timing(_timing_name(event_name), duration_ms, tags=tags)


def artifact_counts(artifact: ChartArtifact) -> tuple[int | None, int | None]:
    chart_type = artifact.chart_type
    encoding = artifact.encoding
    series_count: int | None = None
    category_count: int | None = None
    y_fields = encoding.get("y")
    if isinstance(y_fields, list):
        series_count = len(y_fields)
    elif chart_type in {"grouped_bar", "stacked_bar", "multi_line"} and isinstance(encoding.get("series"), str):
        series_count = None
    elif chart_type == "table" and artifact.data is not None and artifact.data:
        series_count = len(artifact.data[0])

    if artifact.data is not None:
        category_field = encoding.get("category") or encoding.get("x")
        if isinstance(category_field, str):
            category_count = len({row.get(category_field) for row in artifact.data})
    return series_count, category_count


def summary_token_estimate(summary: ChartContextSummary) -> int | None:
    return summary.token_estimate


def _policy_block_summary(error: BaseException | None) -> str | None:
    if not isinstance(error, ChartPolicyDeniedError):
        return None

    message = _optional_text(str(error))
    if message is None:
        return "Visualization blocked by policy."
    if "policy" in message.casefold():
        return message
    return f"Visualization blocked by policy. {message}"


def _metric_operation(event_name: str) -> str:
    if event_name in {CHART_REQUEST_DETECTED, CHART_VALIDATION_STARTED, CHART_VALIDATION_FAILED, CHART_ARTIFACT_BUILD_STARTED, CHART_ARTIFACT_CREATED, CHART_CONTEXT_SUMMARY_CREATED, CHART_ARTIFACT_STORED, CHART_ARTIFACT_DELIVERED, CHART_REQUEST_FAILED, CHART_POLICY_DENIED}:
        return "build"
    return "retrieve"


def _counter_name(event_name: str) -> str:
    mapping = {
        CHART_REQUEST_DETECTED: "backend.visualization.requests.total",
        CHART_VALIDATION_STARTED: "backend.visualization.validation.started.total",
        CHART_VALIDATION_FAILED: "backend.visualization.validation.failed.total",
        CHART_ARTIFACT_BUILD_STARTED: "backend.visualization.artifact_build.started.total",
        CHART_ARTIFACT_CREATED: "backend.visualization.artifact_build.completed.total",
        CHART_CONTEXT_SUMMARY_CREATED: "backend.visualization.context_summary.completed.total",
        CHART_ARTIFACT_STORED: "backend.visualization.artifact_store.writes.total",
        CHART_ARTIFACT_DELIVERED: "backend.visualization.artifact_delivery.total",
        CHART_FOLLOWUP_ARTIFACT_RETRIEVED: "backend.visualization.artifact_store.reads.total",
        CHART_FOLLOWUP_COMPUTATION_COMPLETED: "backend.visualization.followup.computed.total",
        CHART_POLICY_DENIED: "backend.visualization.policy_denials.total",
        CHART_REQUEST_FAILED: "backend.visualization.failures.total",
    }
    return mapping.get(event_name, "backend.visualization.events.total")


def _timing_name(event_name: str) -> str:
    mapping = {
        CHART_ARTIFACT_CREATED: "backend.visualization.artifact_build.duration_ms",
        CHART_CONTEXT_SUMMARY_CREATED: "backend.visualization.context_summary.duration_ms",
        CHART_FOLLOWUP_ARTIFACT_RETRIEVED: "backend.visualization.artifact_retrieval.duration_ms",
        CHART_FOLLOWUP_COMPUTATION_COMPLETED: "backend.visualization.followup_computation.duration_ms",
    }
    return mapping.get(event_name, "backend.visualization.duration_ms")


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None