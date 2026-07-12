from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.visualization.errors import (
    ChartContextSummaryBuildError,
    ChartEncodingError,
    ChartRowLimitExceededError,
    UnsupportedChartTypeError,
)
from app.visualization.models import ChartArtifact, ChartContextSummary
from app.visualization.validators import (
    build_visualization_error_message,
    validate_chart_artifact,
    validate_chart_context_summary,
)


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"
VALIDATION_FIXTURE = json.loads(
    (FIXTURE_DIR / "chart_validation_cases_v1.json").read_text(encoding="utf-8")
)
VALIDATION_CASES = VALIDATION_FIXTURE["cases"]


def _load_json_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VALIDATION_CASES, ids=lambda case: str(case["chart_type"]))
def test_validate_chart_artifact_accepts_every_v1_fixture_case(
    case: dict[str, Any],
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
) -> None:
    artifact = ChartArtifact.model_validate(case["artifact"])

    assert (
        validate_chart_artifact(
            artifact,
            settings=visualization_settings,
            registry=visualization_registry,
            capability_catalog=renderer_capability_catalog,
        )
        is artifact
    )


def test_validate_chart_artifact_rejects_missing_encoding_field(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
) -> None:
    artifact_payload = copy.deepcopy(VALIDATION_CASES[0]["artifact"])
    artifact_payload["encoding"]["y"] = ["missing_value"]
    artifact = ChartArtifact.model_validate(artifact_payload)

    with pytest.raises(ChartEncodingError, match="missing_value"):
        validate_chart_artifact(
            artifact,
            settings=visualization_settings,
            registry=visualization_registry,
            capability_catalog=renderer_capability_catalog,
        )


def test_validate_chart_artifact_rejects_inline_row_limit(
    visualization_settings,
    visualization_registry,
    renderer_capability_catalog,
) -> None:
    artifact_payload = copy.deepcopy(VALIDATION_CASES[0]["artifact"])
    artifact_payload["data"] = artifact_payload["data"] * 2
    artifact = ChartArtifact.model_validate(artifact_payload)
    tight_settings = replace(
        visualization_settings,
        limits=replace(visualization_settings.limits, max_rows_inline=1),
    )

    with pytest.raises(ChartRowLimitExceededError):
        validate_chart_artifact(
            artifact,
            settings=tight_settings,
            registry=visualization_registry,
            capability_catalog=renderer_capability_catalog,
        )


def test_validate_chart_context_summary_accepts_phase0_fixture(
    visualization_settings,
) -> None:
    summary = ChartContextSummary.model_validate(
        _load_json_fixture("chart_context_summary_v1.json")
    )

    assert validate_chart_context_summary(summary, settings=visualization_settings) is summary


def test_validate_chart_context_summary_requires_data_ref_when_exact_followup_is_enabled(
    visualization_settings,
) -> None:
    payload = _load_json_fixture("chart_context_summary_v1.json")
    payload["data_ref"] = None
    summary = ChartContextSummary.model_validate(payload)

    with pytest.raises(ChartContextSummaryBuildError, match="data_ref"):
        validate_chart_context_summary(summary, settings=visualization_settings)


def test_validate_chart_context_summary_rejects_row_level_sample_rows(
    visualization_settings,
) -> None:
    payload = _load_json_fixture("chart_context_summary_v1.json")
    payload["metadata"]["sample_rows"] = [
        {"month": "2026-01", "income": 5200},
    ]
    summary = ChartContextSummary.model_validate(payload)

    with pytest.raises(ChartContextSummaryBuildError, match="sample rows"):
        validate_chart_context_summary(summary, settings=visualization_settings)


def test_unsupported_chart_type_response_fixture_matches_error_mapping(
    visualization_registry,
) -> None:
    response = _load_json_fixture("unsupported_chart_type_response_v1.json")
    error = UnsupportedChartTypeError(
        requested_type="candlestick",
        supported_types=visualization_registry.supported_types,
    )

    assert response["data"]["artifacts"] == []
    assert response["data"]["answer"] == build_visualization_error_message(
        error,
        registry=visualization_registry,
    )