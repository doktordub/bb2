from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.api.schemas import ApiErrorResponse, ChatResponse
from app.visualization.models import ChartArtifact


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"
REQUIRED_CASE_IDS = {
    "bar_income_expense",
    "line_monthly_revenue",
    "pie_revenue_mix",
    "scatter_ad_spend_revenue",
    "histogram_latency",
    "heatmap_incident_hour",
    "gantt_project_plan",
    "table_operational_summary",
    "unsupported_chart_type",
    "missing_data",
    "reference_mode_large_series",
    "expired_artifact",
}


def _load_json(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _catalog() -> dict[str, Any]:
    return _load_json("golden_fixture_catalog_v1.json")


def _validation_cases() -> dict[str, dict[str, Any]]:
    cases = _load_json("chart_validation_cases_v1.json")["cases"]
    return {str(case["chart_type"]): case for case in cases}


def test_phase10_golden_fixture_catalog_covers_required_cases() -> None:
    catalog = _catalog()
    case_ids = [str(case["id"]) for case in catalog["cases"]]

    assert catalog["schema_version"] == "1.0"
    assert set(case_ids) == REQUIRED_CASE_IDS
    assert len(case_ids) == len(set(case_ids))


def test_catalog_entries_resolve_to_current_backend_contracts() -> None:
    catalog = _catalog()
    validation_cases = _validation_cases()

    for case in catalog["cases"]:
        kind = case["kind"]
        if kind == "chart_validation_case":
            artifact = validation_cases[str(case["chart_type"])]["artifact"]
            parsed = ChartArtifact.model_validate(artifact)
            assert parsed.chart_type == case["chart_type"]
            continue

        path = FIXTURE_DIR / str(case["path"])
        assert path.is_file()

        if kind == "artifact_fixture":
            parsed = ChartArtifact.model_validate(_load_json(str(case["path"])))
            assert parsed.data_mode == "reference"
            assert parsed.data is None
            continue

        if kind == "chat_response_fixture":
            parsed = ChatResponse.model_validate(_load_json(str(case["path"])))
            if case["id"] == "unsupported_chart_type":
                assert parsed.data.artifacts == []
            if case["id"] == "missing_data":
                assert "need" in parsed.data.answer.lower()
            continue

        if kind == "api_error_fixture":
            parsed = ApiErrorResponse.model_validate(_load_json(str(case["path"])))
            assert parsed.error.code == "artifact_not_found"
            continue

        raise AssertionError(f"Unsupported golden fixture kind: {kind}")


def test_reference_mode_fixture_matches_public_v1_shape() -> None:
    artifact = ChartArtifact.model_validate(_load_json("reference_mode_large_series_v1.json"))

    assert artifact.chart_type == "line"
    assert artifact.renderer == "echarts"
    assert artifact.data_mode == "reference"
    assert artifact.data is None
    assert artifact.data_ref == "artifact://session_vis_reference_001/chart_reference_large_series_001"