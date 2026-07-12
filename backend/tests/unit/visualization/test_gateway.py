from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.persistence.sqlite_visualization_artifact_store import SqliteVisualizationArtifactStore
from app.config.view import ObservabilitySettings
from app.observability.metrics import InMemoryMetricsRecorder
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.orchestration.errors import OrchestrationCancelledError
from app.policy.factory import build_policy_runtime
from app.testing.fakes import FakeConfigurationView, FakeVisualizationGateway
from app.testing.fakes.fake_trace import FakeTraceStore
from app.visualization.artifact_store import (
    InMemoryVisualizationArtifactStore,
    build_visualization_artifact_scope_from_context,
)
from app.visualization.chart_spec_builder import ChartSpecBuilder
from app.visualization.chart_summary_builder import ChartSummaryBuilder
from app.visualization.errors import ChartDataValidationError, ChartPolicyDeniedError
from app.visualization.gateway import DefaultVisualizationGateway, build_visualization_runtime
from app.visualization.models import (
    ChartComputedFacts,
    ChartDataSlice,
    ChartRequest,
    VisualizationContext,
)


@pytest.fixture
def visualization_context() -> VisualizationContext:
    return VisualizationContext(
        user_id="user-1",
        session_id="session_vis_001",
        usecase="support_web_chat",
        agent_name="chart_agent",
        trace_id="trace-vis-001",
        policy_scope={"tenant_id": "tenant-1", "project_id": "project-1"},
        config={},
    )


def _build_gateway(
    *,
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    artifact_store: InMemoryVisualizationArtifactStore | None = None,
    build_authorizer=None,
    retrieval_authorizer=None,
) -> DefaultVisualizationGateway:
    return DefaultVisualizationGateway(
        settings=visualization_settings,
        registry=visualization_registry,
        capability_catalog=renderer_capability_catalog,
        spec_builder=ChartSpecBuilder(
            settings=visualization_settings,
            registry=visualization_registry,
            capability_catalog=renderer_capability_catalog,
        ),
        summary_builder=ChartSummaryBuilder(settings=visualization_settings),
        artifact_store=artifact_store,
        build_authorizer=build_authorizer,
        retrieval_authorizer=retrieval_authorizer,
    )


def _build_request_payload() -> dict[str, object]:
    return {
        "chart_type": "bar graph",
        "title": "Revenue by Month",
        "description": "Monthly revenue for Q1.",
        "x_field": "month",
        "y_fields": ["revenue"],
        "data_source": "workflow_state",
    }


def _build_rows() -> list[dict[str, object]]:
    return [
        {"month": "2026-01", "revenue": 1200, "region": "NA"},
        {"month": "2026-02", "revenue": 1350, "region": "NA"},
        {"month": "2026-03", "revenue": 1425, "region": "NA"},
    ]


async def test_default_visualization_gateway_builds_alias_requests_and_persists_artifacts(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    artifact_store = InMemoryVisualizationArtifactStore(settings=visualization_settings)
    gateway = _build_gateway(
        visualization_settings=visualization_settings,
        visualization_registry=visualization_registry,
        renderer_capability_catalog=renderer_capability_catalog,
        artifact_store=artifact_store,
    )

    envelope = await gateway.build_visualization(
        _build_request_payload(),
        _build_rows(),
        visualization_context,
        metadata={"unit": "USD"},
    )

    assert envelope.artifact.chart_type == "bar"
    assert envelope.artifact.metadata == {
        "source": "workflow_state",
        "unit": "USD",
    }
    assert envelope.context_summary.data_ref is not None

    stored = await artifact_store.get_artifact(
        scope=build_visualization_artifact_scope_from_context(visualization_context),
        artifact_id=envelope.artifact.artifact_id,
    )

    assert stored.artifact_id == envelope.artifact.artifact_id


async def test_default_visualization_gateway_retrieves_bounded_slices_and_computed_facts(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    artifact_store = InMemoryVisualizationArtifactStore(settings=visualization_settings)
    gateway = _build_gateway(
        visualization_settings=visualization_settings,
        visualization_registry=visualization_registry,
        renderer_capability_catalog=renderer_capability_catalog,
        artifact_store=artifact_store,
    )
    envelope = await gateway.build_visualization(
        _build_request_payload(),
        _build_rows(),
        visualization_context,
    )

    data_slice = await gateway.retrieve_chart_artifact(
        envelope.artifact.artifact_id,
        visualization_context,
        return_type="data_slice",
        fields=["month", "revenue"],
        max_rows=2,
    )
    facts = await gateway.retrieve_chart_artifact(
        envelope.artifact.artifact_id,
        visualization_context,
        return_type="computed_facts",
        value_fields=["revenue"],
    )

    assert isinstance(data_slice, ChartDataSlice)
    assert data_slice.fields == ["month", "revenue"]
    assert data_slice.row_count == 2
    assert isinstance(facts, ChartComputedFacts)
    assert facts.facts["row_count"] == 3
    assert facts.facts["metric_fields"] == ["revenue"]


async def test_default_visualization_gateway_normalizes_authorizer_failures(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    artifact_store = InMemoryVisualizationArtifactStore(settings=visualization_settings)

    def fail(_request: object) -> None:
        raise ValueError("bad chart input")

    gateway = _build_gateway(
        visualization_settings=visualization_settings,
        visualization_registry=visualization_registry,
        renderer_capability_catalog=renderer_capability_catalog,
        artifact_store=artifact_store,
        build_authorizer=fail,
    )

    with pytest.raises(ChartDataValidationError, match="bad chart input"):
        await gateway.build_visualization(
            _build_request_payload(),
            _build_rows(),
            visualization_context,
        )


async def test_default_visualization_gateway_propagates_cancellation_tokens(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    artifact_store = InMemoryVisualizationArtifactStore(settings=visualization_settings)
    gateway = _build_gateway(
        visualization_settings=visualization_settings,
        visualization_registry=visualization_registry,
        renderer_capability_catalog=renderer_capability_catalog,
        artifact_store=artifact_store,
    )
    cancellation_token = asyncio.Event()
    cancellation_token.set()

    with pytest.raises(OrchestrationCancelledError):
        await gateway.build_visualization(
            _build_request_payload(),
            _build_rows(),
            visualization_context,
            cancellation_token=cancellation_token,
        )


async def test_default_visualization_gateway_blocks_exact_retrieval_when_disabled(
    visualization_settings,
    visualization_registry,
    visualization_context,
) -> None:
    restricted_settings = replace(
        visualization_settings,
        artifact_store=replace(
            visualization_settings.artifact_store,
            exact_followup_retrieval_enabled=False,
        ),
    )
    from app.visualization.renderer_capabilities import build_renderer_capability_catalog

    restricted_catalog = build_renderer_capability_catalog(
        settings=restricted_settings,
        registry=visualization_registry,
    )
    artifact_store = InMemoryVisualizationArtifactStore(settings=restricted_settings)
    gateway = _build_gateway(
        visualization_settings=restricted_settings,
        visualization_registry=visualization_registry,
        renderer_capability_catalog=restricted_catalog,
        artifact_store=artifact_store,
    )
    envelope = await gateway.build_visualization(
        _build_request_payload(),
        _build_rows(),
        visualization_context,
    )

    with pytest.raises(ChartPolicyDeniedError, match="disabled"):
        await gateway.retrieve_chart_artifact(
            envelope.artifact.artifact_id,
            visualization_context,
            return_type="computed_facts",
        )


def test_visualization_runtime_factory_builds_a_default_gateway_bundle() -> None:
    runtime = build_visualization_runtime(
        FakeConfigurationView(
            {
                "visualization": {
                    "enabled": True,
                    "artifact_store": {
                        "enabled": True,
                        "provider": "memory",
                        "ttl_seconds": 900,
                        "exact_followup_retrieval_enabled": True,
                    },
                }
            }
        )
    )

    assert isinstance(runtime.gateway, DefaultVisualizationGateway)
    assert isinstance(runtime.artifact_store, InMemoryVisualizationArtifactStore)
    assert runtime.gateway.supported_chart_types()[0] == "bar"
    assert runtime.gateway.renderer_capabilities().renderer == "echarts"


def test_visualization_runtime_factory_builds_a_sqlite_artifact_store(tmp_path) -> None:
    runtime = build_visualization_runtime(
        FakeConfigurationView(
            {
                "app": {"data_dir": tmp_path.as_posix()},
                "visualization": {
                    "enabled": True,
                    "artifact_store": {
                        "enabled": True,
                        "provider": "sqlite",
                        "ttl_seconds": 900,
                        "allow_reference_data_mode": True,
                        "public_retrieval_enabled": True,
                        "retrieval_endpoint": "/artifacts/{artifact_id}",
                        "exact_followup_retrieval_enabled": True,
                    },
                },
            }
        )
    )

    assert isinstance(runtime.gateway, DefaultVisualizationGateway)
    assert isinstance(runtime.artifact_store, SqliteVisualizationArtifactStore)
    assert runtime.artifact_store.database_path.name == "visualization_artifacts.db"


async def test_fake_visualization_gateway_builds_and_retrieves_default_results(
    visualization_context,
) -> None:
    gateway = FakeVisualizationGateway()
    envelope = await gateway.build_visualization(
        ChartRequest(
            chart_type="bar",
            title="Revenue by Month",
            x_field="month",
            y_fields=["revenue"],
            data_source="workflow_state",
        ),
        _build_rows(),
        visualization_context,
    )
    facts = await gateway.retrieve_chart_artifact(
        envelope.artifact.artifact_id,
        visualization_context,
        return_type="computed_facts",
        value_fields=["revenue"],
    )

    assert envelope.artifact.chart_type == "bar"
    assert facts.artifact_id == envelope.artifact.artifact_id
    assert gateway.supported_chart_types()[0] == "bar"


def _build_runtime_config(*, visualization_policy_enabled: bool) -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {"strategy": "direct_agent", "fallback_strategy": "direct_agent"},
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "chart_agent",
                        "allowed_usecases": ["support_web_chat"],
                    }
                },
                "usecases": {
                    "support_web_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "chart_agent",
                        "allowed_agents": ["chart_agent"],
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "chart_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                }
            },
            "visualization": {
                "artifact_store": {
                    "enabled": True,
                    "provider": "memory",
                    "ttl_seconds": 900,
                    "exact_followup_retrieval_enabled": True,
                }
            },
            "policy": {
                "default_profile": "default",
                "profiles": {
                    "default": {
                        "visualization": {
                            "enabled": visualization_policy_enabled,
                        }
                    }
                },
            },
        }
    )


def _build_trace_settings() -> ObservabilitySettings:
    return ObservabilitySettings(
        log_level="INFO",
        structured_logging=True,
        trace_enabled=True,
        trace_payloads_enabled=True,
        trace_store_required=True,
        redact_secrets=True,
        include_stack_traces_in_logs=False,
        include_stack_traces_in_traces=False,
        max_trace_payload_chars=4000,
        slow_request_ms=5000,
        slow_llm_call_ms=30000,
        slow_tool_call_ms=10000,
        metrics_enabled=True,
    )


async def test_visualization_runtime_factory_wires_policy_and_observability(
    visualization_context,
) -> None:
    config = _build_runtime_config(visualization_policy_enabled=True)
    metrics = InMemoryMetricsRecorder()
    policy_runtime = build_policy_runtime(config, metrics=metrics)
    trace_store = FakeTraceStore()
    trace_recorder = TraceRecorder(
        store=trace_store,
        settings=_build_trace_settings(),
        redactor=Redactor(redact_secrets=True, max_chars=4000),
        policy_service=policy_runtime.service,
        config=config,
    )

    runtime = build_visualization_runtime(
        config,
        policy_service=policy_runtime.service,
        metrics=metrics,
        trace_recorder=trace_recorder,
    )

    envelope = await runtime.gateway.build_visualization(
        _build_request_payload(),
        _build_rows(),
        visualization_context,
    )

    assert envelope.artifact.chart_type == "bar"
    event_names = [event.resolved_event_name for event in trace_store.events]
    assert "chart_request_detected" in event_names
    assert "chart_artifact_created" in event_names
    assert "chart_context_summary_created" in event_names
    assert all("rows" not in event.payload for event in trace_store.events)
    assert all("data" not in event.payload for event in trace_store.events)

    snapshot = metrics.snapshot()
    assert any(sample.name == "backend.visualization.requests.total" for sample in snapshot["counters"])
    assert any(sample.name == "backend.visualization.artifact_build.duration_ms" for sample in snapshot["timings"])


async def test_visualization_runtime_factory_applies_policy_denials(
    visualization_context,
) -> None:
    config = _build_runtime_config(visualization_policy_enabled=False)
    policy_runtime = build_policy_runtime(config)
    trace_store = FakeTraceStore()
    trace_recorder = TraceRecorder(
        store=trace_store,
        settings=_build_trace_settings(),
        redactor=Redactor(redact_secrets=True, max_chars=4000),
        policy_service=policy_runtime.service,
        config=config,
    )

    runtime = build_visualization_runtime(
        config,
        policy_service=policy_runtime.service,
        trace_recorder=trace_recorder,
    )

    with pytest.raises(ChartPolicyDeniedError, match="Visualization is disabled"):
        await runtime.gateway.build_visualization(
            _build_request_payload(),
            _build_rows(),
            visualization_context,
        )

    assert trace_store.events[-1].resolved_event_name == "chart_policy_denied"
    assert trace_store.events[-1].payload["policy_block_summary"] == "Visualization blocked by policy. Visualization is disabled for this use case."