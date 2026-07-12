"""In-memory fake visualization gateway for contract-focused tests."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from app.visualization.errors import ChartArtifactNotFoundError
from app.visualization.gateway import VisualizationRetrievalKind
from app.visualization.models import (
    CANONICAL_CHART_TYPES,
    ChartArtifact,
    ChartArtifactEnvelope,
    ChartComputedFacts,
    ChartContextSummary,
    ChartDataSlice,
    ChartRequest,
    RendererCapabilities,
    VisualizationContext,
)


@dataclass(slots=True)
class FakeVisualizationGateway:
    """Deterministic fake visualization gateway for agent, orchestration, and API tests."""

    envelope: ChartArtifactEnvelope | None = None
    build_error: Exception | None = None
    retrieval_error: Exception | None = None
    supported_types: tuple[str, ...] = CANONICAL_CHART_TYPES
    capabilities: RendererCapabilities | None = None
    retrieval_results: dict[tuple[str, VisualizationRetrievalKind], object] = field(
        default_factory=dict
    )
    build_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieve_calls: list[dict[str, Any]] = field(default_factory=list)
    _built_envelopes: dict[str, ChartArtifactEnvelope] = field(default_factory=dict, init=False)

    async def build_visualization(
        self,
        request: ChartRequest | Mapping[str, Any],
        data: Sequence[Mapping[str, Any]],
        context: VisualizationContext,
        *,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
        cancellation_token: object | None = None,
    ) -> ChartArtifactEnvelope:
        del cancellation_token
        self.build_calls.append(
            {
                "request": copy.deepcopy(
                    request.model_dump(mode="python")
                    if isinstance(request, ChartRequest)
                    else dict(request)
                ),
                "data": [dict(row) for row in data],
                "context": context.model_dump(mode="python"),
                "metadata": dict(metadata or {}),
                "warnings": list(warnings or ()),
            }
        )
        if self.build_error is not None:
            raise self.build_error

        resolved = self.envelope or self._build_default_envelope(
            request=request,
            data=data,
            context=context,
            metadata=metadata,
            warnings=warnings,
        )
        self._built_envelopes[resolved.artifact.artifact_id] = resolved.model_copy(deep=True)
        return resolved.model_copy(deep=True)

    async def retrieve_chart_artifact(
        self,
        artifact_id: str,
        context: VisualizationContext,
        *,
        return_type: VisualizationRetrievalKind = "artifact",
        fields: Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
        value_fields: Sequence[str] | None = None,
        cancellation_token: object | None = None,
    ) -> ChartArtifact | ChartDataSlice | ChartComputedFacts:
        del cancellation_token
        self.retrieve_calls.append(
            {
                "artifact_id": artifact_id,
                "context": context.model_dump(mode="python"),
                "return_type": return_type,
                "fields": list(fields or ()),
                "filters": dict(filters or {}),
                "max_rows": max_rows,
                "value_fields": list(value_fields or ()),
            }
        )
        if self.retrieval_error is not None:
            raise self.retrieval_error

        configured = self.retrieval_results.get((artifact_id, return_type))
        if isinstance(configured, ChartArtifact):
            return configured.model_copy(deep=True)
        if isinstance(configured, ChartDataSlice):
            return configured.model_copy(deep=True)
        if isinstance(configured, ChartComputedFacts):
            return configured.model_copy(deep=True)

        envelope = self._built_envelopes.get(artifact_id)
        if envelope is None:
            raise ChartArtifactNotFoundError(
                "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
            )

        if return_type == "artifact":
            return envelope.artifact.model_copy(deep=True)

        rows = [dict(row) for row in envelope.artifact.data or []]
        if return_type == "data_slice":
            selected_fields = list(fields or (rows[0].keys() if rows else ()))
            bounded_rows = rows[:max_rows] if max_rows is not None else rows
            projected_rows = [
                {field_name: row.get(field_name) for field_name in selected_fields}
                for row in bounded_rows
            ]
            return ChartDataSlice(
                artifact_id=envelope.artifact.artifact_id,
                chart_type=envelope.artifact.chart_type,
                data_ref=envelope.context_summary.data_ref,
                fields=selected_fields,
                rows=projected_rows,
                row_count=len(projected_rows),
                truncated=len(projected_rows) < len(rows),
                metadata={"provider": "fake"},
            )

        metric_fields = list(value_fields or envelope.context_summary.y_fields)
        return ChartComputedFacts(
            artifact_id=envelope.artifact.artifact_id,
            chart_type=envelope.artifact.chart_type,
            summary_text=envelope.context_summary.summary_text,
            aggregate_stats={"row_count": len(rows)},
            extrema={},
            trend_summary={},
            facts={
                "metric_fields": metric_fields,
                "available_fields": list(rows[0].keys()) if rows else [],
                "filters": dict(filters or {}),
            },
            data_ref=envelope.context_summary.data_ref,
            metadata={"provider": "fake"},
        )

    def supported_chart_types(self) -> list[str]:
        return list(self.supported_types)

    def renderer_capabilities(self) -> RendererCapabilities:
        if self.capabilities is not None:
            return self.capabilities.model_copy(deep=True)
        return RendererCapabilities(
            renderer="echarts",
            supported_spec_versions=["1.0"],
            supported_chart_types=[cast(Any, chart_type) for chart_type in self.supported_types],
            supported_data_modes=["inline", "reference"],
            supports_reference_data=True,
            max_series=12,
            max_categories=100,
            metadata={"provider": "fake"},
        )

    def _build_default_envelope(
        self,
        *,
        request: ChartRequest | Mapping[str, Any],
        data: Sequence[Mapping[str, Any]],
        context: VisualizationContext,
        metadata: Mapping[str, Any] | None,
        warnings: Sequence[str] | None,
    ) -> ChartArtifactEnvelope:
        normalized_request = (
            request
            if isinstance(request, ChartRequest)
            else ChartRequest.model_validate(dict(request))
        )
        artifact_id = f"fake-chart-{len(self.build_calls)}"
        rows = [dict(row) for row in data]
        summary_y_fields = list(normalized_request.y_fields)
        if not summary_y_fields and normalized_request.value_field:
            summary_y_fields = [normalized_request.value_field]
        artifact = ChartArtifact(
            artifact_id=artifact_id,
            chart_type=normalized_request.chart_type,
            title=normalized_request.title,
            description=normalized_request.description,
            renderer="echarts",
            spec_version="1.0",
            data_mode="inline",
            data=rows,
            data_ref=None,
            encoding=_build_fake_encoding(normalized_request),
            options=dict(normalized_request.options),
            warnings=list(warnings or ()),
            metadata=dict(metadata or {}),
        )
        summary = ChartContextSummary(
            artifact_id=artifact_id,
            chart_type=normalized_request.chart_type,
            title=normalized_request.title,
            description=normalized_request.description,
            renderer="echarts",
            data_source=normalized_request.data_source,
            x_field=normalized_request.x_field or normalized_request.category_field,
            y_fields=summary_y_fields,
            series_field=normalized_request.series_field,
            row_count=len(rows),
            series_count=max(1, len(summary_y_fields) or (1 if normalized_request.series_field else 0)),
            category_count=len(rows),
            time_range=None,
            summary_text=(
                f"Fake {normalized_request.chart_type.replace('_', ' ')} chart with {len(rows)} rows."
            ),
            key_insights=[f"Generated by fake visualization gateway for {context.session_id}."],
            aggregate_stats={"row_count": len(rows)},
            extrema={},
            trend_summary={},
            warnings=list(warnings or ()),
            data_ref=f"artifact://{context.session_id}/{artifact_id}",
            token_estimate=24,
            metadata={"provider": "fake"},
        )
        return ChartArtifactEnvelope(artifact=artifact, context_summary=summary)


def _build_fake_encoding(request: ChartRequest) -> dict[str, Any]:
    if request.chart_type in {"pie", "donut", "treemap"}:
        return {
            "category": request.category_field or request.x_field or "category",
            "value": request.value_field or (request.y_fields[0] if request.y_fields else "value"),
        }
    encoding: dict[str, Any] = {}
    if request.x_field is not None:
        encoding["x"] = request.x_field
    elif request.category_field is not None:
        encoding["x"] = request.category_field
    if request.y_fields:
        encoding["y"] = list(request.y_fields)
    elif request.value_field is not None:
        encoding["value"] = request.value_field
    if request.series_field is not None:
        encoding["series"] = request.series_field
    if request.time_field is not None:
        encoding["time"] = request.time_field
    return encoding


__all__ = ["FakeVisualizationGateway"]