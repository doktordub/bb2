"""Visualization gateway composition, retrieval flows, and runtime assembly."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol, TypeAlias

from app.config.view import get_visualization_settings
from app.contracts.config import ConfigurationView
from app.contracts.errors import PolicyDeniedError
from app.contracts.policy import PolicyService
from app.orchestration.cancellation import raise_if_cancelled
from app.orchestration.errors import OrchestrationCancelledError
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder
from app.observability.tracing import TraceRecorder
from app.persistence.sqlite_visualization_artifact_store import SqliteVisualizationArtifactStore
from app.visualization.artifact_store import (
    InMemoryVisualizationArtifactStore,
    VisualizationArtifactStore,
    build_visualization_artifact_scope_from_context,
)
from app.visualization.chart_data import NormalizedChartData, normalize_chart_data
from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.chart_spec_builder import ChartSpecBuilder
from app.visualization.chart_summary_builder import ChartSummaryBuilder
from app.visualization.computations import VisualizationComputationService
from app.visualization.errors import (
    ChartArtifactNotFoundError,
    ChartDataMissingError,
    ChartDataValidationError,
    ChartPolicyDeniedError,
    UnsupportedRendererError,
    VisualizationError,
)
from app.visualization.models import (
    ChartArtifact,
    ChartArtifactEnvelope,
    ChartComputedFacts,
    ChartDataSlice,
    ChartRequest,
    RendererCapabilities,
    VisualizationContext,
)
from app.visualization.observability import (
    VisualizationGatewayObserver,
    artifact_counts,
    summary_token_estimate,
)
from app.visualization.policy import VisualizationPolicyAuthorizer
from app.visualization.renderer_capabilities import (
    RendererCapabilityCatalog,
    build_renderer_capability_catalog,
)
from app.visualization.settings import VisualizationSettings
from app.visualization.validators import validate_chart_artifact, validate_chart_context_summary

VisualizationRetrievalKind: TypeAlias = Literal[
    "artifact",
    "data_slice",
    "computed_facts",
]


@dataclass(frozen=True, slots=True)
class VisualizationBuildAuthorization:
    """Normalized visualization build inputs exposed to optional policy hooks."""

    stage: Literal["pre_build", "post_artifact", "post_summary"]
    request: ChartRequest
    normalized_data: NormalizedChartData
    context: VisualizationContext
    renderer: str
    artifact: ChartArtifact | None = None
    summary_token_estimate: int | None = None


@dataclass(frozen=True, slots=True)
class VisualizationRetrievalAuthorization:
    """Normalized visualization retrieval inputs exposed to optional policy hooks."""

    artifact_id: str
    context: VisualizationContext
    return_type: VisualizationRetrievalKind
    fields: tuple[str, ...]
    filters: dict[str, Any]
    max_rows: int | None
    value_fields: tuple[str, ...]


class VisualizationBuildAuthorizer(Protocol):
    """Optional async/sync authorizer hook invoked before artifact construction."""

    def __call__(
        self,
        request: VisualizationBuildAuthorization,
    ) -> Awaitable[None] | None:
        ...


class VisualizationRetrievalAuthorizer(Protocol):
    """Optional async/sync authorizer hook invoked before artifact retrieval."""

    def __call__(
        self,
        request: VisualizationRetrievalAuthorization,
    ) -> Awaitable[None] | None:
        ...


class VisualizationGateway(Protocol):
    """Backend-owned visualization boundary used by agents and orchestration."""

    async def build_visualization(
        self,
        request: ChartRequest | Mapping[str, Any],
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        context: VisualizationContext,
        *,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
        cancellation_token: object | None = None,
    ) -> ChartArtifactEnvelope:
        ...

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
        ...

    def supported_chart_types(self) -> list[str]:
        ...

    def renderer_capabilities(self) -> RendererCapabilities:
        ...


@dataclass(slots=True)
class DefaultVisualizationGateway:
    """Default implementation that composes validation, builders, and artifact retrieval."""

    settings: VisualizationSettings
    registry: ChartTypeRegistry
    capability_catalog: RendererCapabilityCatalog
    spec_builder: ChartSpecBuilder
    summary_builder: ChartSummaryBuilder
    artifact_store: VisualizationArtifactStore | None = None
    build_authorizer: VisualizationBuildAuthorizer | None = None
    retrieval_authorizer: VisualizationRetrievalAuthorizer | None = None
    observer: VisualizationGatewayObserver | None = None

    def __post_init__(self) -> None:
        if self.settings.artifact_store.enabled and self.artifact_store is None:
            raise ValueError(
                "Visualization artifact storage is enabled but no artifact store was provided."
            )

    async def build_visualization(
        self,
        request: ChartRequest | Mapping[str, Any],
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        context: VisualizationContext,
        *,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
        cancellation_token: object | None = None,
    ) -> ChartArtifactEnvelope:
        raise_if_cancelled(cancellation_token)

        try:
            started_at = perf_counter()
            normalized_request = self._normalize_request(request)
            renderer = self._resolve_renderer()
            normalized_data = data if isinstance(data, NormalizedChartData) else normalize_chart_data(data)

            await self._record_observation(
                event_name="chart_request_detected",
                context=context,
                chart_type=normalized_request.chart_type,
                renderer=renderer,
                data_source=normalized_request.data_source,
                row_count=normalized_data.row_count,
                status="started",
            )

            await self._authorize_build(
                stage="pre_build",
                request=normalized_request,
                normalized_data=normalized_data,
                context=context,
                renderer=renderer,
            )
            raise_if_cancelled(cancellation_token)

            await self._record_observation(
                event_name="chart_validation_started",
                context=context,
                chart_type=normalized_request.chart_type,
                renderer=renderer,
                data_source=normalized_request.data_source,
                row_count=normalized_data.row_count,
            )
            await self._record_observation(
                event_name="chart_artifact_build_started",
                context=context,
                chart_type=normalized_request.chart_type,
                renderer=renderer,
                data_source=normalized_request.data_source,
                row_count=normalized_data.row_count,
                status="started",
            )

            artifact = self.spec_builder.build(
                request=normalized_request,
                data=normalized_data,
                context=context,
                metadata=metadata,
                warnings=warnings,
            )
            artifact = validate_chart_artifact(
                artifact,
                settings=self.settings,
                registry=self.registry,
                capability_catalog=self.capability_catalog,
            )
            await self._authorize_build(
                stage="post_artifact",
                request=normalized_request,
                normalized_data=normalized_data,
                context=context,
                renderer=renderer,
                artifact=artifact,
            )
            series_count, category_count = artifact_counts(artifact)
            await self._record_observation(
                event_name="chart_artifact_created",
                context=context,
                chart_type=artifact.chart_type,
                renderer=artifact.renderer,
                data_source=normalized_request.data_source,
                data_mode=artifact.data_mode,
                artifact_id=artifact.artifact_id,
                row_count=normalized_data.row_count,
                series_count=series_count,
                category_count=category_count,
                duration_ms=int((perf_counter() - started_at) * 1000),
            )
            raise_if_cancelled(cancellation_token)

            summary = self.summary_builder.build(
                request=normalized_request,
                artifact=artifact,
                data=normalized_data,
                context=context,
                metadata=metadata,
                warnings=warnings,
            )
            summary = validate_chart_context_summary(summary, settings=self.settings)
            await self._authorize_build(
                stage="post_summary",
                request=normalized_request,
                normalized_data=normalized_data,
                context=context,
                renderer=renderer,
                artifact=artifact,
                summary_token_estimate=summary.token_estimate,
            )
            await self._record_observation(
                event_name="chart_context_summary_created",
                context=context,
                chart_type=artifact.chart_type,
                renderer=artifact.renderer,
                data_source=normalized_request.data_source,
                data_mode=artifact.data_mode,
                artifact_id=artifact.artifact_id,
                row_count=normalized_data.row_count,
                token_estimate=summary_token_estimate(summary),
                duration_ms=int((perf_counter() - started_at) * 1000),
            )
            envelope = ChartArtifactEnvelope(artifact=artifact, context_summary=summary)

            if self.artifact_store is not None:
                scope = build_visualization_artifact_scope_from_context(context)
                await self.artifact_store.save_artifact(
                    scope=scope,
                    artifact=envelope.artifact,
                    context_summary=envelope.context_summary,
                    data=normalized_data,
                )
                await self._record_observation(
                    event_name="chart_artifact_stored",
                    context=context,
                    chart_type=artifact.chart_type,
                    renderer=artifact.renderer,
                    data_source=normalized_request.data_source,
                    data_mode=artifact.data_mode,
                    artifact_id=artifact.artifact_id,
                    row_count=normalized_data.row_count,
                )

            raise_if_cancelled(cancellation_token)
            await self._record_observation(
                event_name="chart_artifact_delivered",
                context=context,
                chart_type=artifact.chart_type,
                renderer=artifact.renderer,
                data_source=normalized_request.data_source,
                data_mode=artifact.data_mode,
                artifact_id=artifact.artifact_id,
                row_count=normalized_data.row_count,
                duration_ms=int((perf_counter() - started_at) * 1000),
            )
            return envelope
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, OrchestrationCancelledError)):
                raise
            normalized_error = _normalize_visualization_error(exc)
            await self._record_failure(
                context=context,
                error=normalized_error,
            )
            raise normalized_error from exc

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
        raise_if_cancelled(cancellation_token)

        try:
            started_at = perf_counter()
            normalized_artifact_id = _normalize_artifact_id(artifact_id)
            if self.artifact_store is None:
                raise ChartDataMissingError(
                    "I can answer follow-up chart questions only when chart retrieval is enabled."
                )

            normalized_fields = tuple(_normalize_optional_text_list(fields))
            normalized_value_fields = tuple(_normalize_optional_text_list(value_fields))
            normalized_filters = dict(filters or {})

            await self._authorize_retrieval(
                artifact_id=normalized_artifact_id,
                context=context,
                return_type=return_type,
                fields=normalized_fields,
                filters=normalized_filters,
                max_rows=max_rows,
                value_fields=normalized_value_fields,
            )
            raise_if_cancelled(cancellation_token)

            scope = build_visualization_artifact_scope_from_context(context)

            if return_type == "artifact":
                artifact = await self.artifact_store.get_artifact(
                    scope=scope,
                    artifact_id=normalized_artifact_id,
                )
                if artifact.data_mode == "reference":
                    data_slice = await self.artifact_store.get_data_slice(
                        scope=scope,
                        artifact_id=normalized_artifact_id,
                    )
                    artifact_payload = artifact.model_dump(mode="python")
                    artifact_payload.update(
                        {
                            "data_mode": "inline",
                            "data": [dict(row) for row in data_slice.rows],
                            "data_ref": None,
                        }
                    )
                    artifact = ChartArtifact.model_validate(artifact_payload)
                await self._record_observation(
                    event_name="chart_followup_artifact_retrieved",
                    context=context,
                    chart_type=artifact.chart_type,
                    renderer=artifact.renderer,
                    data_mode=artifact.data_mode,
                    artifact_id=artifact.artifact_id,
                    return_type=return_type,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                )
                return artifact

            if not self.settings.artifact_store.exact_followup_retrieval_enabled:
                raise ChartPolicyDeniedError(
                    "Exact chart follow-up retrieval is disabled for this use case."
                )

            if return_type == "data_slice":
                data_slice = await self.artifact_store.get_data_slice(
                    scope=scope,
                    artifact_id=normalized_artifact_id,
                    fields=normalized_fields or None,
                    filters=normalized_filters or None,
                    max_rows=max_rows,
                )
                await self._record_observation(
                    event_name="chart_followup_artifact_retrieved",
                    context=context,
                    chart_type=data_slice.chart_type,
                    artifact_id=data_slice.artifact_id,
                    data_mode="reference" if data_slice.data_ref else "inline",
                    return_type=return_type,
                    row_count=data_slice.row_count,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                )
                return data_slice

            if return_type == "computed_facts":
                facts = await self.artifact_store.compute_facts(
                    scope=scope,
                    artifact_id=normalized_artifact_id,
                    filters=normalized_filters or None,
                    value_fields=normalized_value_fields or None,
                )
                await self._record_observation(
                    event_name="chart_followup_computation_completed",
                    context=context,
                    chart_type=facts.chart_type,
                    artifact_id=facts.artifact_id,
                    data_mode="reference" if facts.data_ref else "inline",
                    return_type=return_type,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                )
                return facts

            raise ChartDataValidationError(
                f"Unsupported visualization retrieval type '{return_type}'."
            )
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, OrchestrationCancelledError)):
                raise
            normalized_error = _normalize_visualization_error(exc)
            await self._record_failure(
                context=context,
                error=normalized_error,
            )
            raise normalized_error from exc

    def supported_chart_types(self) -> list[str]:
        return list(self.registry.supported_types)

    def renderer_capabilities(self) -> RendererCapabilities:
        renderer = self._resolve_renderer()
        return self.capability_catalog.describe_renderer(renderer)

    async def _authorize_build(
        self,
        *,
        stage: Literal["pre_build", "post_artifact", "post_summary"],
        request: ChartRequest,
        normalized_data: NormalizedChartData,
        context: VisualizationContext,
        renderer: str,
        artifact: ChartArtifact | None = None,
        summary_token_estimate: int | None = None,
    ) -> None:
        if self.build_authorizer is None:
            return
        await _await_if_needed(
            self.build_authorizer(
                VisualizationBuildAuthorization(
                    stage=stage,
                    request=request,
                    normalized_data=normalized_data,
                    context=context,
                    renderer=renderer,
                    artifact=artifact,
                    summary_token_estimate=summary_token_estimate,
                )
            )
        )

    async def _authorize_retrieval(
        self,
        *,
        artifact_id: str,
        context: VisualizationContext,
        return_type: VisualizationRetrievalKind,
        fields: tuple[str, ...],
        filters: dict[str, Any],
        max_rows: int | None,
        value_fields: tuple[str, ...],
    ) -> None:
        if self.retrieval_authorizer is None:
            return
        await _await_if_needed(
            self.retrieval_authorizer(
                VisualizationRetrievalAuthorization(
                    artifact_id=artifact_id,
                    context=context,
                    return_type=return_type,
                    fields=fields,
                    filters=filters,
                    max_rows=max_rows,
                    value_fields=value_fields,
                )
            )
        )

    def _normalize_request(
        self,
        request: ChartRequest | Mapping[str, Any],
    ) -> ChartRequest:
        payload = (
            request.model_dump(mode="python")
            if isinstance(request, ChartRequest)
            else dict(request)
        )
        payload["chart_type"] = self.registry.normalize(str(payload.get("chart_type", "")))
        return ChartRequest.model_validate(payload)

    def _resolve_renderer(self) -> str:
        renderer = self.settings.default_renderer.strip()
        if renderer not in self.settings.allowed_renderers:
            raise UnsupportedRendererError(
                renderer=renderer,
                supported_renderers=self.settings.allowed_renderers,
            )
        self.capability_catalog.describe_renderer(renderer)
        return renderer

    async def _record_observation(
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
        if self.observer is None:
            return
        await self.observer.record(
            event_name=event_name,
            context=context,
            chart_type=chart_type,
            renderer=renderer,
            data_source=data_source,
            data_mode=data_mode,
            artifact_id=artifact_id,
            row_count=row_count,
            series_count=series_count,
            category_count=category_count,
            token_estimate=token_estimate,
            return_type=return_type,
            status=status,
            duration_ms=duration_ms,
            error=error,
        )

    async def _record_failure(
        self,
        *,
        context: VisualizationContext,
        error: VisualizationError,
    ) -> None:
        event_name = "chart_policy_denied" if isinstance(error, ChartPolicyDeniedError) else "chart_request_failed"
        await self._record_observation(
            event_name=event_name,
            context=context,
            status="failed",
            error=error,
        )


@dataclass(frozen=True, slots=True)
class VisualizationRuntimeBundle:
    """Composed visualization runtime pieces ready for startup wiring."""

    settings: VisualizationSettings
    registry: ChartTypeRegistry
    capability_catalog: RendererCapabilityCatalog
    spec_builder: ChartSpecBuilder
    summary_builder: ChartSummaryBuilder
    computation_service: VisualizationComputationService
    artifact_store: VisualizationArtifactStore | None
    gateway: DefaultVisualizationGateway


def build_visualization_runtime(
    config: ConfigurationView,
    *,
    artifact_store: VisualizationArtifactStore | None = None,
    build_authorizer: VisualizationBuildAuthorizer | None = None,
    retrieval_authorizer: VisualizationRetrievalAuthorizer | None = None,
    policy_service: PolicyService | None = None,
    metrics: MetricsRecorder | None = None,
    trace_recorder: TraceRecorder | None = None,
    observer: VisualizationGatewayObserver | None = None,
) -> VisualizationRuntimeBundle:
    """Build the configured visualization runtime around validated settings."""

    settings = get_visualization_settings(config)
    registry = ChartTypeRegistry(
        allowed_chart_types=settings.allowed_chart_types,
        aliases=settings.aliases,
    )
    capability_catalog = build_renderer_capability_catalog(
        settings=settings,
        registry=registry,
    )
    spec_builder = ChartSpecBuilder(
        settings=settings,
        registry=registry,
        capability_catalog=capability_catalog,
    )
    summary_builder = ChartSummaryBuilder(settings=settings)
    computation_service = VisualizationComputationService(
        settings=settings,
        registry=registry,
        capability_catalog=capability_catalog,
    )
    resolved_store = artifact_store or _build_artifact_store(settings)
    policy_authorizer = (
        VisualizationPolicyAuthorizer(policy_service=policy_service, config=config)
        if policy_service is not None
        else None
    )
    gateway = DefaultVisualizationGateway(
        settings=settings,
        registry=registry,
        capability_catalog=capability_catalog,
        spec_builder=spec_builder,
        summary_builder=summary_builder,
        artifact_store=resolved_store,
        build_authorizer=build_authorizer or (policy_authorizer.authorize_build if policy_authorizer is not None else None),
        retrieval_authorizer=retrieval_authorizer or (policy_authorizer.authorize_retrieval if policy_authorizer is not None else None),
        observer=observer or (VisualizationGatewayObserver(trace_recorder=trace_recorder, metrics=metrics or NoopMetricsRecorder()) if trace_recorder is not None or metrics is not None else None),
    )
    return VisualizationRuntimeBundle(
        settings=settings,
        registry=registry,
        capability_catalog=capability_catalog,
        spec_builder=spec_builder,
        summary_builder=summary_builder,
        computation_service=computation_service,
        artifact_store=resolved_store,
        gateway=gateway,
    )


def build_visualization_gateway(
    config: ConfigurationView,
    *,
    artifact_store: VisualizationArtifactStore | None = None,
    build_authorizer: VisualizationBuildAuthorizer | None = None,
    retrieval_authorizer: VisualizationRetrievalAuthorizer | None = None,
    policy_service: PolicyService | None = None,
    metrics: MetricsRecorder | None = None,
    trace_recorder: TraceRecorder | None = None,
    observer: VisualizationGatewayObserver | None = None,
) -> DefaultVisualizationGateway:
    """Build only the default visualization gateway for callers that do not need the bundle."""

    return build_visualization_runtime(
        config,
        artifact_store=artifact_store,
        build_authorizer=build_authorizer,
        retrieval_authorizer=retrieval_authorizer,
        policy_service=policy_service,
        metrics=metrics,
        trace_recorder=trace_recorder,
        observer=observer,
    ).gateway


def _build_artifact_store(
    settings: VisualizationSettings,
) -> VisualizationArtifactStore | None:
    provider = settings.artifact_store.provider.strip().lower()
    if not settings.artifact_store.enabled or provider in {"", "disabled", "none"}:
        return None
    if provider == "memory":
        return InMemoryVisualizationArtifactStore(settings=settings)
    if provider == "sqlite":
        sqlite_settings = settings.artifact_store.sqlite
        if sqlite_settings is None:
            raise ValueError("SQLite visualization artifact storage requires sqlite settings.")
        return SqliteVisualizationArtifactStore(
            database_path=sqlite_settings.path,
            settings=settings,
            sqlite_settings=sqlite_settings,
        )
    raise ValueError(f"Unsupported visualization artifact store provider: {provider}")


async def _await_if_needed(value: Awaitable[None] | None) -> None:
    if value is None:
        return
    await value


def _normalize_artifact_id(artifact_id: str) -> str:
    normalized = artifact_id.strip()
    if not normalized:
        raise ChartArtifactNotFoundError(
            "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
        )
    return normalized


def _normalize_optional_text_list(values: Sequence[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value).strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _normalize_visualization_error(error: BaseException) -> VisualizationError:
    if isinstance(error, VisualizationError):
        return error
    if isinstance(error, PolicyDeniedError):
        return ChartPolicyDeniedError(
            str(error) or "This chart cannot be generated because it is not allowed for this use case."
        )
    if isinstance(error, PermissionError):
        return ChartPolicyDeniedError(
            str(error) or "This chart cannot be generated because it is not allowed for this use case."
        )
    if isinstance(error, LookupError):
        return ChartArtifactNotFoundError(
            "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
        )
    if isinstance(error, (TypeError, ValueError, KeyError)):
        return ChartDataValidationError(
            str(error) or "The data does not match the requested chart."
        )
    return VisualizationError("Visualization gateway failed.")


__all__ = [
    "DefaultVisualizationGateway",
    "VisualizationBuildAuthorization",
    "VisualizationBuildAuthorizer",
    "VisualizationGateway",
    "VisualizationRetrievalAuthorization",
    "VisualizationRetrievalAuthorizer",
    "VisualizationRetrievalKind",
    "VisualizationRuntimeBundle",
    "build_visualization_gateway",
    "build_visualization_runtime",
]