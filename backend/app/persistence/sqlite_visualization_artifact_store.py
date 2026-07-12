"""SQLite-backed visualization artifact store for restart-safe chart replay."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from app.persistence.serialization import dumps_canonical_json
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite_visualization_artifact_schema import (
    ensure_visualization_artifact_schema,
)
from app.visualization.artifact_store import (
    VisualizationArtifactScope,
    _coerce_store_data,
    _normalize_scope,
    _resolve_data_ref,
    _resolve_retrieval_row_limit,
    _scope_matches,
)
from app.visualization.chart_data import NormalizedChartData
from app.visualization.computations import build_chart_computed_facts, build_chart_data_slice
from app.visualization.errors import (
    ChartArtifactNotFoundError,
    ChartDataMissingError,
    ChartRowLimitExceededError,
)
from app.visualization.models import (
    ChartArtifact,
    ChartComputedFacts,
    ChartContextSummary,
    ChartDataSlice,
)
from app.visualization.settings import (
    VisualizationArtifactStoreSqliteSettings,
    VisualizationSettings,
)


@dataclass(frozen=True, slots=True)
class _StoredVisualizationArtifactRow:
    scope: VisualizationArtifactScope
    artifact: ChartArtifact
    context_summary: ChartContextSummary
    rows: tuple[dict[str, Any], ...]
    fields: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    data_ref: str | None = None


class SqliteVisualizationArtifactStore:
    """Durable visualization artifact store backed by SQLite."""

    def __init__(
        self,
        database_path: Path,
        *,
        settings: VisualizationSettings,
        sqlite_settings: VisualizationArtifactStoreSqliteSettings | None = None,
    ) -> None:
        self._database_path = database_path
        self.settings = settings
        self._sqlite_settings = sqlite_settings or VisualizationArtifactStoreSqliteSettings(
            path=database_path,
            create_parent_dirs=True,
            initialize_schema=True,
            journal_mode="WAL",
            synchronous="NORMAL",
            busy_timeout_ms=5000,
            foreign_keys=True,
            required=True,
        )

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def sqlite_settings(self) -> VisualizationArtifactStoreSqliteSettings:
        return self._sqlite_settings

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def save_artifact(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact: ChartArtifact,
        context_summary: ChartContextSummary,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._save_artifact_sync,
            scope,
            artifact,
            context_summary,
            data,
            ttl_seconds,
        )

    async def get_artifact(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> ChartArtifact:
        record = await asyncio.to_thread(self._get_record_sync, scope, artifact_id)
        return record.artifact.model_copy(deep=True)

    async def get_context_summary(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> ChartContextSummary:
        record = await asyncio.to_thread(self._get_record_sync, scope, artifact_id)
        return record.context_summary.model_copy(deep=True)

    async def delete_session_artifacts(
        self,
        *,
        scope: VisualizationArtifactScope,
    ) -> int:
        return await asyncio.to_thread(self._delete_session_artifacts_sync, scope)

    async def get_data_slice(
        self,
        *,
        scope: VisualizationArtifactScope,
        artifact_id: str,
        fields: Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
    ) -> ChartDataSlice:
        record = await asyncio.to_thread(self._get_record_sync, scope, artifact_id)
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
        record = await asyncio.to_thread(self._get_record_sync, scope, artifact_id)
        return build_chart_computed_facts(
            record.artifact,
            record.rows,
            filters=filters,
            value_fields=value_fields,
            summary_text=record.context_summary.summary_text,
            data_ref=record.data_ref,
        )

    async def purge_expired(self) -> int:
        return await asyncio.to_thread(self._purge_expired_sync)

    def _initialize_sync(self) -> None:
        with open_sqlite_connection(self._database_path, settings=self._sqlite_settings) as connection:
            self._ensure_schema(connection)
            self._purge_expired_on_connection(connection, now=datetime.now(UTC))
            connection.commit()

    def _save_artifact_sync(
        self,
        scope: VisualizationArtifactScope,
        artifact: ChartArtifact,
        context_summary: ChartContextSummary,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData | None,
        ttl_seconds: int | None,
    ) -> str:
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

        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(
            seconds=ttl_seconds or self.settings.artifact_store.ttl_seconds
        )
        rows = normalized.rows_as_list() if normalized is not None else []
        fields = list(normalized.fields) if normalized is not None else []
        data_ref = _resolve_data_ref(
            scope=resolved_scope,
            artifact=artifact,
            context_summary=context_summary,
        )

        with open_sqlite_connection(self._database_path, settings=self._sqlite_settings) as connection:
            self._ensure_schema(connection)
            self._purge_expired_on_connection(connection, now=created_at)
            connection.execute(
                """
                INSERT INTO visualization_artifacts (
                    session_id,
                    artifact_id,
                    user_id,
                    tenant_id,
                    project_id,
                    artifact_json,
                    context_summary_json,
                    rows_json,
                    fields_json,
                    created_at,
                    expires_at,
                    data_ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, artifact_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    tenant_id = excluded.tenant_id,
                    project_id = excluded.project_id,
                    artifact_json = excluded.artifact_json,
                    context_summary_json = excluded.context_summary_json,
                    rows_json = excluded.rows_json,
                    fields_json = excluded.fields_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    data_ref = excluded.data_ref
                """,
                (
                    resolved_scope.session_id,
                    artifact.artifact_id,
                    resolved_scope.user_id,
                    resolved_scope.tenant_id,
                    resolved_scope.project_id,
                    dumps_canonical_json(artifact.model_dump(mode="python")),
                    dumps_canonical_json(context_summary.model_dump(mode="python")),
                    dumps_canonical_json(rows),
                    dumps_canonical_json(fields),
                    created_at.isoformat(),
                    expires_at.isoformat(),
                    data_ref,
                ),
            )
            connection.commit()

        return data_ref or artifact.artifact_id

    def _get_record_sync(
        self,
        scope: VisualizationArtifactScope,
        artifact_id: str,
    ) -> _StoredVisualizationArtifactRow:
        resolved_scope = _normalize_scope(scope)
        with open_sqlite_connection(self._database_path, settings=self._sqlite_settings) as connection:
            self._ensure_schema(connection)
            self._purge_expired_on_connection(connection, now=datetime.now(UTC))
            row = connection.execute(
                """
                SELECT
                    session_id,
                    artifact_id,
                    user_id,
                    tenant_id,
                    project_id,
                    artifact_json,
                    context_summary_json,
                    rows_json,
                    fields_json,
                    created_at,
                    expires_at,
                    data_ref
                FROM visualization_artifacts
                WHERE session_id = ? AND artifact_id = ?
                """,
                (resolved_scope.session_id, artifact_id),
            ).fetchone()

        if row is None:
            raise ChartArtifactNotFoundError(
                "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
            )

        record = self._decode_record_row(row)
        if not _scope_matches(record.scope, resolved_scope):
            raise ChartArtifactNotFoundError(
                "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again."
            )
        return record

    def _delete_session_artifacts_sync(self, scope: VisualizationArtifactScope) -> int:
        resolved_scope = _normalize_scope(scope)
        deleted = 0

        with open_sqlite_connection(self._database_path, settings=self._sqlite_settings) as connection:
            self._ensure_schema(connection)
            self._purge_expired_on_connection(connection, now=datetime.now(UTC))
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    artifact_id,
                    user_id,
                    tenant_id,
                    project_id,
                    artifact_json,
                    context_summary_json,
                    rows_json,
                    fields_json,
                    created_at,
                    expires_at,
                    data_ref
                FROM visualization_artifacts
                WHERE session_id = ?
                """,
                (resolved_scope.session_id,),
            ).fetchall()
            for row in rows:
                record = self._decode_record_row(row)
                if not _scope_matches(record.scope, resolved_scope):
                    continue
                connection.execute(
                    "DELETE FROM visualization_artifacts WHERE session_id = ? AND artifact_id = ?",
                    (record.scope.session_id, record.artifact.artifact_id),
                )
                deleted += 1
            connection.commit()

        return deleted

    def _purge_expired_sync(self) -> int:
        with open_sqlite_connection(self._database_path, settings=self._sqlite_settings) as connection:
            self._ensure_schema(connection)
            deleted = self._purge_expired_on_connection(connection, now=datetime.now(UTC))
            connection.commit()
        return deleted

    def _ensure_schema(self, connection: Connection) -> None:
        if self._sqlite_settings.initialize_schema:
            ensure_visualization_artifact_schema(connection)

    def _purge_expired_on_connection(self, connection: Connection, *, now: datetime) -> int:
        deleted = connection.execute(
            "DELETE FROM visualization_artifacts WHERE expires_at <= ?",
            (now.isoformat(),),
        ).rowcount
        return max(int(deleted or 0), 0)

    def _decode_record_row(self, row: Sequence[Any]) -> _StoredVisualizationArtifactRow:
        (
            session_id,
            _artifact_id,
            user_id,
            tenant_id,
            project_id,
            artifact_json,
            context_summary_json,
            rows_json,
            fields_json,
            created_at,
            expires_at,
            data_ref,
        ) = row
        return _StoredVisualizationArtifactRow(
            scope=VisualizationArtifactScope(
                session_id=str(session_id),
                user_id=_optional_text(user_id),
                tenant_id=_optional_text(tenant_id),
                project_id=_optional_text(project_id),
            ),
            artifact=ChartArtifact.model_validate(_decode_json_value(artifact_json, expected_type=dict)),
            context_summary=ChartContextSummary.model_validate(
                _decode_json_value(context_summary_json, expected_type=dict)
            ),
            rows=tuple(dict(item) for item in _decode_json_value(rows_json, expected_type=list)),
            fields=tuple(str(item) for item in _decode_json_value(fields_json, expected_type=list)),
            created_at=_decode_datetime(created_at),
            expires_at=_decode_datetime(expires_at),
            data_ref=_optional_text(data_ref),
        )


def _decode_json_value(value: Any, *, expected_type: type[dict[str, Any]] | type[list[Any]]) -> Any:
    if not isinstance(value, str):
        raise ValueError("Stored visualization artifact payload is not valid JSON text.")
    payload = json.loads(value)
    if not isinstance(payload, expected_type):
        raise ValueError("Stored visualization artifact payload has an unexpected JSON shape.")
    return payload


def _decode_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Stored visualization artifact timestamp is invalid.")
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["SqliteVisualizationArtifactStore"]