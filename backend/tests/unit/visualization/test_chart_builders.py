from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.visualization.chart_spec_builder import ChartSpecBuilder
from app.visualization.chart_summary_builder import ChartSummaryBuilder, build_chart_context_contribution
from app.visualization.models import ChartArtifact, ChartRequest, VisualizationContext
from app.visualization.renderer_capabilities import build_renderer_capability_catalog


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"
VALIDATION_CASES = json.loads(
    (FIXTURE_DIR / "chart_validation_cases_v1.json").read_text(encoding="utf-8")
)["cases"]


def _request_from_artifact_payload(payload: dict[str, Any]) -> ChartRequest:
    encoding = payload["encoding"]
    options = copy.deepcopy(payload["options"])
    chart_type = payload["chart_type"]
    x_field = None
    category_field = None
    series_field = None
    value_field = None
    time_field = None
    y_fields: list[str] = []

    if chart_type in {"bar", "horizontal_bar", "line", "multi_line", "area", "radar", "box_plot"}:
        x_field = encoding.get("x")
        time_field = encoding.get("time")
        y_value = encoding.get("y")
        y_fields = [y_value] if isinstance(y_value, str) else list(y_value or [])
    elif chart_type in {"grouped_bar", "stacked_bar"}:
        x_field = encoding.get("x")
        y_value = encoding.get("y")
        y_fields = [y_value] if isinstance(y_value, str) else list(y_value or [])
        series_field = encoding.get("series")
        value_field = encoding.get("value")
    elif chart_type in {"pie", "donut", "treemap"}:
        category_field = encoding.get("category")
        value_field = encoding.get("value")
    elif chart_type == "waterfall":
        x_field = encoding.get("x")
        value_field = encoding.get("value")
    elif chart_type == "scatter":
        x_field = encoding.get("x")
        y_fields = [encoding["y"]]
    elif chart_type == "bubble":
        x_field = encoding.get("x")
        y_fields = [encoding["y"]]
        options["size_field"] = encoding["size"]
    elif chart_type == "histogram":
        x_field = encoding.get("x")
    elif chart_type == "heatmap":
        x_field = encoding.get("x")
        series_field = encoding.get("y")
        value_field = encoding.get("value")
        time_field = encoding.get("time")
    elif chart_type == "gantt":
        x_field = encoding.get("task")
        options["start_field"] = encoding["start"]
        options["end_field"] = encoding["end"]

    return ChartRequest(
        chart_type=chart_type,
        title=payload["title"],
        description=payload.get("description"),
        x_field=x_field,
        y_fields=y_fields,
        category_field=category_field,
        series_field=series_field,
        value_field=value_field,
        time_field=time_field,
        options=options,
        data_source=payload["metadata"]["source"],
    )


@pytest.fixture
def visualization_context() -> VisualizationContext:
    return VisualizationContext(
        user_id="user-1",
        session_id="session_vis_001",
        usecase="support_web_chat",
        agent_name="chart_agent",
        trace_id="trace-vis-001",
        policy_scope={},
        config={},
    )


@pytest.mark.parametrize("case", VALIDATION_CASES, ids=lambda case: str(case["chart_type"]))
def test_chart_spec_builder_builds_valid_artifacts_for_all_chart_types(
    case: dict[str, Any],
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    artifact_payload = case["artifact"]
    request = _request_from_artifact_payload(artifact_payload)
    builder = ChartSpecBuilder(
        settings=visualization_settings,
        registry=visualization_registry,
        capability_catalog=renderer_capability_catalog,
    )

    artifact = builder.build(
        request=request,
        data=artifact_payload["data"],
        context=visualization_context,
        metadata={key: value for key, value in artifact_payload["metadata"].items() if key != "source"},
    )

    assert isinstance(artifact, ChartArtifact)
    assert artifact.chart_type == artifact_payload["chart_type"]
    assert artifact.data_mode == "inline"
    assert artifact.data == artifact_payload["data"]
    assert artifact.encoding == artifact_payload["encoding"]
    assert artifact.options == artifact_payload["options"]
    assert artifact.metadata == artifact_payload["metadata"]
    second_artifact = builder.build(
        request=request,
        data=artifact_payload["data"],
        context=visualization_context,
        metadata={key: value for key, value in artifact_payload["metadata"].items() if key != "source"},
    )
    assert artifact.artifact_id == second_artifact.artifact_id


def test_chart_spec_builder_uses_reference_mode_when_inline_limit_is_exceeded(
    visualization_settings,
    visualization_registry,
    visualization_context,
) -> None:
    reference_settings = replace(
        visualization_settings,
        limits=replace(visualization_settings.limits, max_rows_inline=2),
        artifact_store=replace(
            visualization_settings.artifact_store,
            allow_reference_data_mode=True,
            public_retrieval_enabled=True,
        ),
    )
    capability_catalog = build_renderer_capability_catalog(
        settings=reference_settings,
        registry=visualization_registry,
    )
    case = VALIDATION_CASES[1]
    request = _request_from_artifact_payload(case["artifact"])
    builder = ChartSpecBuilder(
        settings=reference_settings,
        registry=visualization_registry,
        capability_catalog=capability_catalog,
    )

    artifact = builder.build(
        request=request,
        data=case["artifact"]["data"],
        context=visualization_context,
        metadata={key: value for key, value in case["artifact"]["metadata"].items() if key != "source"},
    )

    assert artifact.data_mode == "reference"
    assert artifact.data is None
    assert artifact.data_ref == f"artifact://{visualization_context.session_id}/{artifact.artifact_id}"


@pytest.mark.parametrize("case", VALIDATION_CASES, ids=lambda case: str(case["chart_type"]))
def test_chart_summary_builder_builds_prompt_safe_summaries_for_all_chart_types(
    case: dict[str, Any],
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    artifact_payload = case["artifact"]
    request = _request_from_artifact_payload(artifact_payload)
    spec_builder = ChartSpecBuilder(
        settings=visualization_settings,
        registry=visualization_registry,
        capability_catalog=renderer_capability_catalog,
    )
    summary_builder = ChartSummaryBuilder(settings=visualization_settings)
    artifact = spec_builder.build(
        request=request,
        data=artifact_payload["data"],
        context=visualization_context,
        metadata={key: value for key, value in artifact_payload["metadata"].items() if key != "source"},
    )

    summary = summary_builder.build(
        request=request,
        artifact=artifact,
        data=artifact_payload["data"],
        context=visualization_context,
    )
    contribution = build_chart_context_contribution(summary)

    assert summary.artifact_id == artifact.artifact_id
    assert summary.chart_type == artifact.chart_type
    assert summary.row_count == len(artifact_payload["data"])
    assert summary.data_source == artifact_payload["metadata"]["source"]
    assert summary.summary_text
    assert summary.key_insights
    assert summary.aggregate_stats
    assert contribution.kind == "chart_summary"
    assert contribution.source_artifact_id == artifact.artifact_id
    assert contribution.content["artifact_id"] == artifact.artifact_id
    if artifact.chart_type in {"line", "multi_line", "area", "gantt"}:
        assert summary.time_range is not None
    assert "data" not in summary.model_dump(mode="json")
    assert "rows" not in summary.metadata


def test_chart_summary_builder_compacts_to_the_configured_budget(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    tight_settings = replace(
        visualization_settings,
        context_summary=replace(
            visualization_settings.context_summary,
            max_tokens_per_chart_summary=50,
            max_total_visualization_context_tokens=50,
        ),
    )
    case = VALIDATION_CASES[1]
    request = _request_from_artifact_payload(case["artifact"])
    spec_builder = ChartSpecBuilder(
        settings=visualization_settings,
        registry=visualization_registry,
        capability_catalog=renderer_capability_catalog,
    )
    artifact = spec_builder.build(
        request=request,
        data=case["artifact"]["data"],
        context=visualization_context,
        metadata={key: value for key, value in case["artifact"]["metadata"].items() if key != "source"},
    )
    summary_builder = ChartSummaryBuilder(settings=tight_settings)

    summary = summary_builder.build(
        request=request,
        artifact=artifact,
        data=case["artifact"]["data"],
        context=visualization_context,
    )

    assert (summary.token_estimate or 0) <= 50
    assert summary.data_ref is not None


def test_chart_summary_builder_does_not_include_the_full_dataset_in_context(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
    visualization_context,
) -> None:
    request = ChartRequest(
        chart_type="bar",
        title="Revenue by Month",
        x_field="month",
        y_fields=["revenue"],
        data_source="workflow_state",
    )
    data = [
        {"month": f"2026-{index:02d}", "revenue": index * 100, "row_id": f"row-{index:02d}"}
        for index in range(1, 11)
    ]
    spec_builder = ChartSpecBuilder(
        settings=visualization_settings,
        registry=visualization_registry,
        capability_catalog=renderer_capability_catalog,
    )
    artifact = spec_builder.build(
        request=request,
        data=data,
        context=visualization_context,
        metadata={"unit": "USD"},
    )
    summary_builder = ChartSummaryBuilder(settings=visualization_settings)

    summary = summary_builder.build(
        request=request,
        artifact=artifact,
        data=data,
        context=visualization_context,
    )

    rendered_summary = json.dumps(summary.model_dump(mode="json"), sort_keys=True)
    assert "row-01" not in rendered_summary or "row-10" not in rendered_summary
    assert "sample_rows" not in summary.metadata
