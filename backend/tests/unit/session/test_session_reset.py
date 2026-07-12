from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config.view import (
    SessionConcurrencySettings,
    SessionDefaultsSettings,
    SessionHistorySettings,
    SessionIdentifierSettings,
    SessionLifecycleSettings,
    SessionSettings,
    SessionStateSettings,
    SessionTracingSettings,
)
from app.session.mapping import build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_policy import FakePolicyService
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder
from app.visualization.artifact_store import InMemoryVisualizationArtifactStore, build_visualization_artifact_scope
from app.visualization.errors import ChartArtifactNotFoundError
from app.visualization.models import ChartArtifact, ChartContextSummary
from app.visualization.settings import (
    DEFAULT_VISUALIZATION_ALIASES,
    DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST,
    VisualizationArtifactStoreSettings,
    VisualizationContextSummarySettings,
    VisualizationLimitsSettings,
    VisualizationSampleDataSettings,
    VisualizationSettings,
)


def _build_settings() -> SessionSettings:
    return SessionSettings(
        enabled=True,
        identifiers=SessionIdentifierSettings(
            prefix="session",
            accept_client_session_id=True,
            generate_when_missing=True,
            max_length=128,
            allowed_pattern="^[A-Za-z0-9_.:-]{3,128}$",
        ),
        defaults=SessionDefaultsSettings(
            default_user_id="local_user",
            default_usecase="default_chat",
            default_history_limit=50,
            max_history_limit=200,
            timezone_metadata_key="timezone",
        ),
        lifecycle=SessionLifecycleSettings(
            create_on_first_chat=True,
            resume_existing_sessions=True,
            reject_unknown_client_session_id=False,
            update_last_seen_on_load=True,
            save_after_failed_orchestration=True,
            save_after_cancelled_stream=True,
        ),
        concurrency=SessionConcurrencySettings(
            mode="optimistic_version",
            conflict_policy="reject",
            max_retries=1,
        ),
        state=SessionStateSettings(
            save_on_chat_completion=True,
            save_on_stream_completion=True,
            save_on_stream_cancellation=True,
            save_on_stream_failure=True,
            save_each_stream_delta=False,
        ),
        history=SessionHistorySettings(
            enabled=False,
            include_tool_summaries=False,
            include_system_messages=False,
            include_metadata=True,
            max_message_chars=4000,
            redaction_enabled=True,
        ),
        tracing=SessionTracingSettings(
            record_session_created=True,
            record_session_resumed=True,
            record_session_reset=True,
            record_state_loaded=True,
            record_state_saved=True,
            record_history_returned=True,
            record_stream_lifecycle=True,
        ),
    )
def _build_context():
    return build_session_request_context(
        trace_id="trace-session-reset-0001",
        request_id="request-session-reset-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/sessions/session_reset_1/reset",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-reset-0001"},
    )


def _build_visualization_settings() -> VisualizationSettings:
    return VisualizationSettings(
        enabled=True,
        default_renderer="echarts",
        allowed_renderers=("echarts",),
        artifact_spec_version="1.0",
        allowed_chart_types=("bar", "line", "grouped_bar"),
        aliases=dict(DEFAULT_VISUALIZATION_ALIASES),
        safe_metadata_allowlist=DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST,
        limits=VisualizationLimitsSettings(
            max_rows_inline=500,
            max_rows_artifact_store=5000,
            max_series=12,
            max_categories=100,
            max_artifact_bytes=262144,
        ),
        sample_data=VisualizationSampleDataSettings(
            enabled=False,
            require_explicit_opt_in=True,
            max_rows=25,
        ),
        context_summary=VisualizationContextSummarySettings(
            enabled=True,
            mode="summary_only",
            max_tokens_per_chart_summary=600,
            max_chart_summaries_per_session_context=5,
            max_total_visualization_context_tokens=1800,
            include_data_ref=True,
            include_aggregate_stats=True,
            include_extrema=True,
            include_trend_summary=True,
            include_sample_rows=False,
            max_sample_rows=0,
            eviction_policy="most_recent_relevant",
            allow_full_dataset_in_context=False,
        ),
        artifact_store=VisualizationArtifactStoreSettings(
            enabled=True,
            provider="memory",
            ttl_seconds=7200,
            allow_reference_data_mode=True,
            public_retrieval_enabled=False,
            retrieval_endpoint="/artifacts/{artifact_id}",
            exact_followup_retrieval_enabled=True,
        ),
    )


@pytest.mark.asyncio
async def test_reset_session_passes_reason_and_safe_metadata_to_workflow_state() -> None:
    workflow_state = FakeWorkflowStateStore()
    workflow_state.states["session_reset_1"] = {
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
        "workflow": {"current_step": "answered"},
        "metadata": {"loaded_empty": False},
    }
    workflow_state.versions["session_reset_1"] = 2
    trace_store = FakeTraceStore()
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=FakeOrchestrationRuntime(),
        policy_service=FakePolicyService(),
        clock=FakeClock([datetime(2026, 6, 27, 17, 0, tzinfo=UTC)]),
    )

    result = await service.reset_session(
        session_id="session_reset_1",
        reason="user_requested",
        context=_build_context(),
    )

    assert result.reset is True
    assert result.metadata == {"reason": "user_requested"}
    assert workflow_state.reset_calls[0].reason == "user_requested"
    assert workflow_state.reset_calls[0].metadata == {
        "trace_id": "trace-session-reset-0001",
        "request_id": "request-session-reset-0001",
        "user_id": "local_user",
        "user_id_hash": "user_hash_123",
    }
    assert "session_reset_1" not in workflow_state.states
    assert workflow_state.reset_generations["session_reset_1"] == 1
    assert [event.resolved_event_name for event in trace_store.events] == ["session_reset"]


@pytest.mark.asyncio
async def test_reset_session_clears_session_scoped_visualization_artifacts() -> None:
    workflow_state = FakeWorkflowStateStore()
    workflow_state.states["session_reset_1"] = {
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
        "workflow": {"current_step": "answered"},
        "metadata": {"loaded_empty": False},
    }
    workflow_state.versions["session_reset_1"] = 2
    trace_store = FakeTraceStore()
    visualization_store = InMemoryVisualizationArtifactStore(
        settings=_build_visualization_settings(),
        clock=FakeClock([datetime(2026, 6, 27, 17, 0, tzinfo=UTC)] * 4),
    )
    scope = build_visualization_artifact_scope(
        session_id="session_reset_1",
        user_id="local_user",
        scope=None,
    )
    artifact = ChartArtifact(
        artifact_id="chart_reset_001",
        chart_type="bar",
        title="Income by Month",
        renderer="echarts",
        spec_version="1.0",
        data_mode="inline",
        data=[{"month": "2026-01", "amount": 500}],
        encoding={"x": "month", "y": ["amount"]},
        metadata={"source": "workflow_state"},
    )
    summary = ChartContextSummary(
        artifact_id=artifact.artifact_id,
        chart_type=artifact.chart_type,
        title=artifact.title,
        renderer=artifact.renderer,
        data_source="workflow_state",
        x_field="month",
        y_fields=["amount"],
        row_count=1,
        series_count=1,
        summary_text="Income is 500 in January.",
        data_ref="artifact://session_reset_1/chart_reset_001",
    )
    await visualization_store.save_artifact(
        scope=scope,
        artifact=artifact,
        context_summary=summary,
        data=artifact.data,
    )

    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=FakeOrchestrationRuntime(),
        policy_service=FakePolicyService(),
        clock=FakeClock([datetime(2026, 6, 27, 17, 0, tzinfo=UTC)]),
        visualization_artifact_store=visualization_store,
    )

    result = await service.reset_session(
        session_id="session_reset_1",
        reason="user_requested",
        context=_build_context(),
    )

    assert result.metadata == {
        "reason": "user_requested",
        "visualization_artifacts_cleared": 1,
    }
    with pytest.raises(ChartArtifactNotFoundError):
        await visualization_store.get_artifact(scope=scope, artifact_id=artifact.artifact_id)
