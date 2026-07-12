from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.persistence.sqlite_visualization_artifact_store import SqliteVisualizationArtifactStore
from app.testing.fakes.fake_clock import FakeClock
from app.visualization.artifact_store import (
    InMemoryVisualizationArtifactStore,
    build_visualization_artifact_scope,
    build_visualization_artifact_scope_from_context,
)
from app.visualization.chart_spec_builder import ChartSpecBuilder
from app.visualization.chart_summary_builder import ChartSummaryBuilder
from app.visualization.computations import VisualizationComputationService
from app.visualization.errors import ChartArtifactNotFoundError, ChartFollowupAmbiguousError
from app.visualization.models import ChartRequest, VisualizationContext
from app.visualization.renderer_capabilities import build_renderer_capability_catalog
from app.visualization.settings import VisualizationArtifactStoreSqliteSettings


def _series_request() -> ChartRequest:
    return ChartRequest(
        chart_type="grouped_bar",
        title="Income vs Expense by Month",
        x_field="month",
        series_field="series",
        value_field="amount",
        data_source="tool",
    )


def _series_data() -> list[dict[str, Any]]:
    return [
        {"month": "2026-01", "series": "income", "amount": 500},
        {"month": "2026-01", "series": "expense", "amount": 300},
        {"month": "2026-02", "series": "income", "amount": 450},
        {"month": "2026-02", "series": "expense", "amount": 350},
    ]


def _visualization_context() -> VisualizationContext:
    return VisualizationContext(
        user_id="user-1",
        session_id="session_vis_001",
        usecase="support_web_chat",
        agent_name="chart_agent",
        trace_id="trace-vis-001",
        policy_scope={"tenant_id": "tenant-7", "project_id": "project-9"},
        config={},
    )


def _reference_settings(visualization_settings):
    return replace(
        visualization_settings,
        artifact_store=replace(
            visualization_settings.artifact_store,
            provider="memory",
            enabled=True,
            allow_reference_data_mode=True,
            public_retrieval_enabled=True,
            ttl_seconds=60,
        ),
    )


def _sqlite_reference_settings(visualization_settings, tmp_path: Path):
    return replace(
        visualization_settings,
        artifact_store=replace(
            visualization_settings.artifact_store,
            provider="sqlite",
            enabled=True,
            allow_reference_data_mode=True,
            public_retrieval_enabled=True,
            ttl_seconds=60,
            sqlite=VisualizationArtifactStoreSqliteSettings(
                path=tmp_path / "visualization_artifacts.db",
                create_parent_dirs=True,
                initialize_schema=True,
                journal_mode="WAL",
                synchronous="NORMAL",
                busy_timeout_ms=5000,
                foreign_keys=True,
                required=True,
            ),
        ),
    )


def _build_bundle(
    *,
    visualization_settings,
    visualization_registry,
    visualization_context: VisualizationContext,
) -> tuple[ChartRequest, list[dict[str, Any]], object, object]:
    request = _series_request()
    data = _series_data()
    capability_catalog = build_renderer_capability_catalog(
        settings=visualization_settings,
        registry=visualization_registry,
    )
    spec_builder = ChartSpecBuilder(
        settings=visualization_settings,
        registry=visualization_registry,
        capability_catalog=capability_catalog,
    )
    summary_builder = ChartSummaryBuilder(settings=visualization_settings)
    artifact = spec_builder.build(
        request=request,
        data=data,
        context=visualization_context,
        metadata={"unit": "USD", "currency": "USD"},
    )
    summary = summary_builder.build(
        request=request,
        artifact=artifact,
        data=data,
        context=visualization_context,
    )
    return request, data, artifact, summary


@pytest.mark.asyncio
async def test_in_memory_artifact_store_saves_retrieves_scopes_and_expires(
    visualization_settings,
    visualization_registry,
) -> None:
    settings = _reference_settings(visualization_settings)
    context = _visualization_context()
    _, data, artifact, summary = _build_bundle(
        visualization_settings=settings,
        visualization_registry=visualization_registry,
        visualization_context=context,
    )
    created_at = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)
    clock = FakeClock(
        [
            created_at,
            created_at,
            created_at,
            created_at,
            created_at + timedelta(seconds=61),
        ]
    )
    store = InMemoryVisualizationArtifactStore(settings=settings, clock=clock)
    scope = build_visualization_artifact_scope_from_context(context)

    saved_ref = await store.save_artifact(
        scope=scope,
        artifact=artifact,
        context_summary=summary,
        data=data,
    )

    assert saved_ref == summary.data_ref

    loaded_artifact = await store.get_artifact(scope=scope, artifact_id=artifact.artifact_id)
    loaded_summary = await store.get_context_summary(scope=scope, artifact_id=artifact.artifact_id)

    assert loaded_artifact.artifact_id == artifact.artifact_id
    assert loaded_summary.data_ref == summary.data_ref

    wrong_scope = build_visualization_artifact_scope(
        session_id=context.session_id,
        user_id="other-user",
        scope=context.policy_scope,
    )
    with pytest.raises(ChartArtifactNotFoundError):
        await store.get_artifact(scope=wrong_scope, artifact_id=artifact.artifact_id)

    with pytest.raises(ChartArtifactNotFoundError):
        await store.get_artifact(scope=scope, artifact_id=artifact.artifact_id)


@pytest.mark.asyncio
async def test_in_memory_artifact_store_returns_bounded_slices_and_facts(
    visualization_settings,
    visualization_registry,
) -> None:
    settings = _reference_settings(visualization_settings)
    context = _visualization_context()
    _, data, artifact, summary = _build_bundle(
        visualization_settings=settings,
        visualization_registry=visualization_registry,
        visualization_context=context,
    )
    store = InMemoryVisualizationArtifactStore(
        settings=settings,
        clock=FakeClock([datetime(2026, 7, 10, 9, 0, tzinfo=UTC)] * 4),
    )
    scope = build_visualization_artifact_scope_from_context(context)
    await store.save_artifact(
        scope=scope,
        artifact=artifact,
        context_summary=summary,
        data=data,
    )

    data_slice = await store.get_data_slice(
        scope=scope,
        artifact_id=artifact.artifact_id,
        fields=["month", "series", "amount"],
        max_rows=2,
    )
    facts = await store.compute_facts(scope=scope, artifact_id=artifact.artifact_id)

    assert data_slice.fields == ["month", "series", "amount"]
    assert data_slice.row_count == 2
    assert data_slice.truncated is True
    assert data_slice.metadata["matched_row_count"] == 4
    assert facts.aggregate_stats["amount"]["total"] == 1600
    assert facts.extrema["amount"]["max"]["value"] == 500
    assert facts.data_ref == summary.data_ref


@pytest.mark.asyncio
async def test_computation_service_supports_exact_lookup_period_filter_comparison_and_reuse(
    visualization_settings,
    visualization_registry,
) -> None:
    settings = _reference_settings(visualization_settings)
    context = _visualization_context()
    _, data, artifact, _summary = _build_bundle(
        visualization_settings=settings,
        visualization_registry=visualization_registry,
        visualization_context=context,
    )
    capability_catalog = build_renderer_capability_catalog(
        settings=settings,
        registry=visualization_registry,
    )
    service = VisualizationComputationService(
        settings=settings,
        registry=visualization_registry,
        capability_catalog=capability_catalog,
    )

    exact = service.lookup_exact_value(
        artifact=artifact,
        data=data,
        match_field="month",
        match_value="2026-02",
        series_field="series",
        series_value="income",
        value_field="amount",
    )
    period = service.filter_by_period(
        artifact=artifact,
        data=data,
        field_name="month",
        start="2026-02",
        end="2026-02",
        fields=["month", "series", "amount"],
    )
    comparison = service.compare_series(
        artifact=artifact,
        data=data,
        series_field="series",
        left_series="income",
        right_series="expense",
        value_field="amount",
        x_field="month",
    )
    reused = service.reuse_chart_data_for_request(
        request=ChartRequest(
            chart_type="multi_line",
            title="Income vs Expense Trend",
            x_field="month",
            series_field="series",
            value_field="amount",
            time_field="month",
            data_source="tool",
        ),
        data=data,
        context=context,
        metadata={"unit": "USD", "currency": "USD"},
    )

    assert exact.facts["value"] == 450
    assert period.row_count == 2
    assert all(row["month"] == "2026-02" for row in period.rows)
    assert comparison.facts["difference"] == 300
    assert comparison.facts["by_x"]["2026-01"]["difference"] == 200
    assert reused.chart_type == "multi_line"
    assert reused.encoding["series"] == "series"
    assert reused.encoding["value"] == "amount"

    with pytest.raises(ChartFollowupAmbiguousError):
        service.lookup_exact_value(
            artifact=artifact,
            data=data,
            match_field="month",
            match_value="2026-01",
            value_field="amount",
        )


@pytest.mark.asyncio
async def test_in_memory_artifact_store_delete_session_artifacts_removes_cached_records(
    visualization_settings,
    visualization_registry,
) -> None:
    settings = _reference_settings(visualization_settings)
    context = _visualization_context()
    _, data, artifact, summary = _build_bundle(
        visualization_settings=settings,
        visualization_registry=visualization_registry,
        visualization_context=context,
    )
    store = InMemoryVisualizationArtifactStore(
        settings=settings,
        clock=FakeClock([datetime(2026, 7, 10, 9, 0, tzinfo=UTC)] * 3),
    )
    scope = build_visualization_artifact_scope_from_context(context)
    await store.save_artifact(
        scope=scope,
        artifact=artifact,
        context_summary=summary,
        data=data,
    )

    deleted = await store.delete_session_artifacts(scope=scope)

    assert deleted == 1
    with pytest.raises(ChartArtifactNotFoundError):
        await store.get_context_summary(scope=scope, artifact_id=artifact.artifact_id)


@pytest.mark.asyncio
async def test_sqlite_artifact_store_survives_restart_and_enforces_scope(
    tmp_path: Path,
    visualization_settings,
    visualization_registry,
) -> None:
    settings = _sqlite_reference_settings(visualization_settings, tmp_path)
    context = _visualization_context()
    _, data, artifact, summary = _build_bundle(
        visualization_settings=settings,
        visualization_registry=visualization_registry,
        visualization_context=context,
    )
    sqlite_settings = settings.artifact_store.sqlite
    assert sqlite_settings is not None

    scope = build_visualization_artifact_scope_from_context(context)
    store = SqliteVisualizationArtifactStore(
        database_path=sqlite_settings.path,
        settings=settings,
        sqlite_settings=sqlite_settings,
    )
    saved_ref = await store.save_artifact(
        scope=scope,
        artifact=artifact,
        context_summary=summary,
        data=data,
    )

    restarted = SqliteVisualizationArtifactStore(
        database_path=sqlite_settings.path,
        settings=settings,
        sqlite_settings=sqlite_settings,
    )
    loaded_artifact = await restarted.get_artifact(scope=scope, artifact_id=artifact.artifact_id)
    loaded_summary = await restarted.get_context_summary(scope=scope, artifact_id=artifact.artifact_id)

    assert saved_ref == summary.data_ref
    assert loaded_artifact.artifact_id == artifact.artifact_id
    assert loaded_summary.data_ref == summary.data_ref

    wrong_scope = build_visualization_artifact_scope(
        session_id=context.session_id,
        user_id="other-user",
        scope=context.policy_scope,
    )
    with pytest.raises(ChartArtifactNotFoundError):
        await restarted.get_artifact(scope=wrong_scope, artifact_id=artifact.artifact_id)


@pytest.mark.asyncio
async def test_sqlite_artifact_store_delete_session_artifacts_removes_durable_records(
    tmp_path: Path,
    visualization_settings,
    visualization_registry,
) -> None:
    settings = _sqlite_reference_settings(visualization_settings, tmp_path)
    context = _visualization_context()
    _, data, artifact, summary = _build_bundle(
        visualization_settings=settings,
        visualization_registry=visualization_registry,
        visualization_context=context,
    )
    sqlite_settings = settings.artifact_store.sqlite
    assert sqlite_settings is not None

    scope = build_visualization_artifact_scope_from_context(context)
    store = SqliteVisualizationArtifactStore(
        database_path=sqlite_settings.path,
        settings=settings,
        sqlite_settings=sqlite_settings,
    )
    await store.save_artifact(
        scope=scope,
        artifact=artifact,
        context_summary=summary,
        data=data,
    )

    deleted = await store.delete_session_artifacts(scope=scope)

    assert deleted == 1
    with pytest.raises(ChartArtifactNotFoundError):
        await store.get_context_summary(scope=scope, artifact_id=artifact.artifact_id)