"""Session-scoped artifact storage for deterministic visualization follow-ups."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.visualization.chart_data import NormalizedChartData, normalize_chart_data
from app.visualization.computations import build_chart_computed_facts, build_chart_data_slice
from app.visualization.errors import (
    ChartArtifactNotFoundError,
    ChartDataMissingError,
    ChartRowLimitExceededError,
)
from app.visualization.models import ChartArtifact, ChartComputedFacts, ChartContextSummary, ChartDataSlice, VisualizationContext
from app.visualization.settings import VisualizationSettings


class VisualizationArtifactClock(Protocol):
    """Clock protocol used to test TTL-based visualization storage."""

    def now(self) -> datetime:
        ...


@dataclass(frozen=True, slots=True)
class SystemVisualizationArtifactClock:
    """System clock used by the default in-memory visualization store."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class VisualizationArtifactScope:
    """Authorized retrieval scope for one session-scoped chart artifact."""

    session_id: str
    user_id: str | None = None
    tenant_id: str | None = None
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class StoredVisualizationArtifact:
    """Internal record stored by the session-scoped visualization cache."""

    scope: VisualizationArtifactScope
    artifact: ChartArtifact
    context_summary: ChartContextSummary
    rows: tuple[dict[str, Any], ...]
    fields: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    data_ref: str | None = None


class VisualizationArtifactStore(Protocol):
    """Artifact retrieval boundary used by the visualization gateway and session reset."""

    async def save_artifact(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact: ChartArtifact,
        context_summary: ChartContextSummary,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        ...

    async def get_artifact(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> ChartArtifact:
        ...

    async def get_context_summary(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> ChartContextSummary:
        ...

    async def delete_session_artifacts(
        self,
        *,
        scope: VisualizationArtifactScope,
    ) -> int:
        ...

    async def get_data_slice(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
        fields: Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
    ) -> ChartDataSlice:
        ...

    async def compute_facts(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
        filters: Mapping[str, Any] | None = None,
        value_fields: Sequence[str] | None = None,
    ) -> ChartComputedFacts:
        ...


@dataclass(slots=True)
class InMemoryVisualizationArtifactStore:
    """V1 artifact store backed by a session-scoped in-memory cache."""

    settings: VisualizationSettings
    clock: VisualizationArtifactClock = field(default_factory=SystemVisualizationArtifactClock)
    _records: dict[str, dict[str, StoredVisualizationArtifact]] = field(default_factory=dict)

    async def save_artifact(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact: ChartArtifact,
        context_summary: ChartContextSummary,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Persist one artifact, summary, and bounded source rows for exact follow-ups."""

        now = self.clock.now()
        self._purge_expired(now=now)
        resolved_scope = _normalize_scope(scope)
        normalized = _coerce_store_data(artifact=artifact, data=data)
        if normalized is None and (
            self.settings.artifact_store.exact_followup_retrieval_enabled
            or artifact.data_mode == "reference"
        ):
            raise ChartDataMissingError(
                "Exact follow-up retrieval requires bounded chart rows to be cached."
            )
        if normalized is not None and normalized.row_count > self.settings.limits.max_rows_artifact_store:
            raise ChartRowLimitExceededError(
                "The dataset exceeds the configured visualization row limit."
            )

        created_at = now
        expires_at = created_at + timedelta(
            seconds=ttl_seconds or self.settings.artifact_store.ttl_seconds
        )
        rows = tuple(copy.deepcopy(normalized.rows_as_list())) if normalized is not None else ()
        fields = tuple(normalized.fields) if normalized is not None else ()
        record = StoredVisualizationArtifact(
            scope=resolved_scope,
            artifact=artifact.model_copy(deep=True),
            context_summary=context_summary.model_copy(deep=True),
            rows=rows,
            fields=fields,
            created_at=created_at,
            expires_at=expires_at,
            data_ref=_resolve_data_ref(
                scope=resolved_scope,
                artifact=artifact,
                context_summary=context_summary,
            ),
        )
        self._records.setdefault(resolved_scope.session_id, {})[artifact.artifact_id] = record
        return record.data_ref or artifact.artifact_id

    async def get_artifact(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> ChartArtifact:
        record = self._get_record(scope=scope, artifact_id=artifact_id)
        return record.artifact.model_copy(deep=True)

    async def get_context_summary(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> ChartContextSummary:
        record = self._get_record(scope=scope, artifact_id=artifact_id)
        return record.context_summary.model_copy(deep=True)

    async def delete_session_artifacts(
        self,
        *,
        scope: VisualizationArtifactScope,
    ) -> int:
        """Remove all cached visualization records owned by one session scope."""

        self._purge_expired(now=self.clock.now())
        resolved_scope = _normalize_scope(scope)
        session_records = self._records.get(resolved_scope.session_id)
        if not session_records:
            return 0

        deleted = 0
        for artifact_id in list(session_records.keys()):
            record = session_records[artifact_id]
            if _scope_matches(record.scope, resolved_scope):
                deleted += 1
                del session_records[artifact_id]

        if not session_records:
            self._records.pop(resolved_scope.session_id, None)
        return deleted

    async def get_data_slice(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
        fields: Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
    ) -> ChartDataSlice:
        record = self._get_record(scope=scope, artifact_id=artifact_id)
        return build_chart_data_slice(
            record.artifact,
            record.rows,
            fields=fields,
            filters=filters,
            max_rows=_resolve_retrieval_row_limit(self.settings, max_rows),
            data_ref=record.data_ref,
        )

    async def compute_facts(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
        filters: Mapping[str, Any] | None = None,
        value_fields: Sequence[str] | None = None,
    ) -> ChartComputedFacts:
        record = self._get_record(scope=scope, artifact_id=artifact_id)
        return build_chart_computed_facts(
            record.artifact,
            record.rows,
            filters=filters,
            value_fields=value_fields,
            summary_text=record.context_summary.summary_text,
            data_ref=record.data_ref,
        )

    async def purge_expired(self) -> int:
        """Public cleanup entry point used by focused tests and future lifecycle hooks."""

        return self._purge_expired(now=self.clock.now())

    def _get_record(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> StoredVisualizationArtifact:
        self._purge_expired(now=self.clock.now())
        resolved_scope = _normalize_scope(scope)
        session_records = self._records.get(resolved_scope.session_id)
        if session_records is None:
            raise ChartArtifactNotFoundError(
                "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
            )
        record = session_records.get(artifact_id)
        if record is None or not _scope_matches(record.scope, resolved_scope):
            raise ChartArtifactNotFoundError(
                "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
            )
        return record

    def _purge_expired(self, *, now: datetime | None = None) -> int:
        reference_time = now or self.clock.now()
        deleted = 0
        for session_id in list(self._records.keys()):
            session_records = self._records[session_id]
            for artifact_id in list(session_records.keys()):
                if session_records[artifact_id].expires_at <= reference_time:
                    del session_records[artifact_id]
                    deleted += 1
            if not session_records:
                del self._records[session_id]
        return deleted


def build_visualization_artifact_scope(
    *,
    session_id: str,
    user_id: str | None,
    scope: Mapping[str, Any] | None = None,
) -> VisualizationArtifactScope:
    """Build one artifact ownership scope from session and request metadata."""

    return VisualizationArtifactScope(
        session_id=_normalize_optional_text(session_id, label="session_id", required=True) or "",
        user_id=_normalize_optional_text(user_id, label="user_id", required=False),
        tenant_id=_extract_scope_value(scope, "tenant_id", "tenant"),
        project_id=_extract_scope_value(scope, "project_id", "project"),
    )


def build_visualization_artifact_scope_from_context(
    context: VisualizationContext,
) -> VisualizationArtifactScope:
    """Build one artifact ownership scope from the visualization context contract."""

    return build_visualization_artifact_scope(
        session_id=context.session_id,
        user_id=context.user_id,
        scope=context.policy_scope,
    )


def _coerce_store_data(
    *,
    artifact: ChartArtifact,
    data: Sequence[Mapping[str, Any]] | NormalizedChartData | None,
) -> NormalizedChartData | None:
    if isinstance(data, NormalizedChartData):
        return data
    if data is not None:
        return normalize_chart_data(data)
    if artifact.data is not None:
        return normalize_chart_data(artifact.data)
    return None


def _normalize_scope(scope: VisualizationArtifactScope) -> VisualizationArtifactScope:
    session_id = _normalize_optional_text(scope.session_id, label="session_id", required=True) or ""
    return VisualizationArtifactScope(
        session_id=session_id,
        user_id=_normalize_optional_text(scope.user_id, label="user_id", required=False),
        tenant_id=_normalize_optional_text(scope.tenant_id, label="tenant_id", required=False),
        project_id=_normalize_optional_text(scope.project_id, label="project_id", required=False),
    )


def _normalize_optional_text(
    value: str | None,
    *,
    label: str,
    required: bool,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{label} must not be empty.")
        return None
    normalized = value.strip()
    if not normalized:
        if required:
            raise ValueError(f"{label} must not be empty.")
        return None
    return normalized


def _extract_scope_value(scope: Mapping[str, Any] | None, *keys: str) -> str | None:
    if scope is None:
        return None
    for key in keys:
        raw_value = scope.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def _scope_matches(
    stored_scope: VisualizationArtifactScope,
    requested_scope: VisualizationArtifactScope,
) -> bool:
    if stored_scope.session_id != requested_scope.session_id:
        return False
    for field_name in ("user_id", "tenant_id", "project_id"):
        stored_value = getattr(stored_scope, field_name)
        requested_value = getattr(requested_scope, field_name)
        if stored_value is not None and stored_value != requested_value:
            return False
    return True


def _resolve_data_ref(
    *,
    scope: VisualizationArtifactScope,
    artifact: ChartArtifact,
    context_summary: ChartContextSummary,
) -> str | None:
    if artifact.data_ref:
        return artifact.data_ref
    if context_summary.data_ref:
        return context_summary.data_ref
    return f"artifact://{scope.session_id}/{artifact.artifact_id}"


def _resolve_retrieval_row_limit(
    settings: VisualizationSettings,
    max_rows: int | None,
) -> int:
    if max_rows is None:
        return settings.limits.max_rows_artifact_store
    return max(1, min(max_rows, settings.limits.max_rows_artifact_store))


__all__ = [
    "InMemoryVisualizationArtifactStore",
    "StoredVisualizationArtifact",
    "SystemVisualizationArtifactClock",
    "VisualizationArtifactClock",
    "VisualizationArtifactScope",
    "VisualizationArtifactStore",
    "build_visualization_artifact_scope",
    "build_visualization_artifact_scope_from_context",
]