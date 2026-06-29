"""Persistence composition helpers for backend startup wiring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import inspect
from typing import Any

from app.config.view import ObservabilitySettings, get_observability_settings
from app.contracts.config import ConfigurationView
from app.contracts.health import HEALTH_NOT_CONFIGURED, HealthStatus
from app.contracts.state import WorkflowStateStore
from app.contracts.trace import TraceEvent, TraceStore
from app.persistence.errors import (
    PersistenceConfigurationError,
    TraceStoreError,
)
from app.persistence.settings import (
    PersistenceSettings,
    TracePersistenceSettings,
    WorkflowStatePersistenceSettings,
    get_persistence_settings,
)
from app.observability.metrics import MetricsRecorder, build_metrics_recorder
from app.observability.tracing import WorkflowStateObserver
from app.persistence.sqlite_trace_store import SqliteTraceStore
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore
from app.testing.fakes import FakeTraceStore, FakeWorkflowStateStore


@dataclass(frozen=True, slots=True)
class PersistenceBundle:
    """Concrete persistence services built for the backend runtime."""

    settings: PersistenceSettings
    workflow_state: WorkflowStateStore
    trace_store: TraceStore

    async def close(self) -> None:
        """Close persistence resources that hold open handles."""

        for component in (self.trace_store, self.workflow_state):
            close = getattr(component, "close", None)
            if not callable(close):
                continue
            result = close()
            if inspect.isawaitable(result):
                await result


async def build_persistence_bundle(
    config: ConfigurationView,
    *,
    observability: ObservabilitySettings | None = None,
    metrics: MetricsRecorder | None = None,
) -> PersistenceBundle:
    """Build all persistence services needed during backend startup."""

    return await build_persistence_bundle_with_observability(
        config,
        observability=observability,
        metrics=metrics,
    )


async def build_persistence_bundle_with_observability(
    config: ConfigurationView,
    *,
    observability: ObservabilitySettings | None = None,
    metrics: MetricsRecorder | None = None,
) -> PersistenceBundle:
    """Build persistence services and attach workflow-state observability hooks."""

    settings = get_persistence_settings(config)
    resolved_observability = observability or get_observability_settings(config)
    resolved_metrics = metrics or build_metrics_recorder(
        enabled=resolved_observability.metrics_enabled
    )
    trace_store = await _build_trace_store(settings.trace, metrics=resolved_metrics)
    workflow_state = await _build_workflow_state_store(
        settings.workflow_state,
        observer=WorkflowStateObserver(
            store=trace_store,
            metrics=resolved_metrics,
            trace_enabled=resolved_observability.trace_enabled,
        ),
    )
    return PersistenceBundle(
        settings=settings,
        workflow_state=workflow_state,
        trace_store=trace_store,
    )


async def _build_workflow_state_store(
    settings: WorkflowStatePersistenceSettings,
    *,
    observer: WorkflowStateObserver | None = None,
) -> WorkflowStateStore:
    if settings.provider == "fake":
        return FakeWorkflowStateStore()

    if settings.provider != "sqlite" or settings.sqlite is None:
        raise PersistenceConfigurationError(
            f"Unsupported workflow-state store provider: {settings.provider}"
        )

    store = SqliteWorkflowStateStore(
        settings.sqlite.path,
        settings=settings.sqlite,
        observer=observer,
    )
    await store.initialize()
    return store


async def _build_trace_store(
    settings: TracePersistenceSettings,
    *,
    metrics: MetricsRecorder | None = None,
) -> TraceStore:
    if settings.provider == "fake":
        return FakeTraceStore()

    if settings.provider == "sqlite" and settings.sqlite is not None:
        try:
            store = SqliteTraceStore(
                settings.sqlite.path,
                settings=settings.sqlite,
                metrics=metrics,
            )
            await store.initialize()
            return store
        except Exception:
            if settings.required:
                raise
            return _UnavailableTraceStore(
                provider=settings.provider,
                required=settings.required,
                reason="initialization_failed",
                status="degraded",
            )

    if settings.required:
        raise PersistenceConfigurationError(
            f"Unsupported trace store provider: {settings.provider}"
        )

    return _UnavailableTraceStore(
        provider=settings.provider,
        required=settings.required,
        reason="unsupported_provider",
        status=HEALTH_NOT_CONFIGURED,
    )


class _UnavailableTraceStore:
    def __init__(
        self,
        *,
        provider: str,
        required: bool,
        reason: str,
        status: HealthStatus,
    ) -> None:
        self._provider = provider
        self._required = required
        self._reason = reason
        self._status = status

    async def record_event(self, event: TraceEvent) -> None:
        return None

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        return None

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> Any:
        raise TraceStoreError("Trace store is not available.")

    async def search_traces(self, *, filters: Any) -> list[Any]:
        raise TraceStoreError("Trace store is not available.")

    async def health(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "configured": False,
            "provider": self._provider,
            "required": self._required,
            "reason": self._reason,
        }
