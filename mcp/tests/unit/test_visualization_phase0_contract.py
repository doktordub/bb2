from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.tools_base.results import ToolResultEnvelope, ToolResultSummary


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "visualization"

EXPECTED_ERROR_CODES = {
    "invalid_query",
    "unsupported_metric",
    "unsupported_dimension",
    "invalid_date_range",
    "unauthorized_scope",
    "provider_unavailable",
    "timeout",
    "rate_limited",
    "result_too_large",
    "schema_mismatch",
    "internal_error",
}


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _build_validator(name: str) -> Draft202012Validator:
    schema = _load_json(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_query_metric_series_request_fixture_matches_frozen_schema() -> None:
    validator = _build_validator("query_metric_series_request_v1.schema.json")
    request_fixture = _load_json("query_metric_series_request_v1.json")

    validator.validate(request_fixture)

    assert request_fixture["metric_names"] == ["income", "expense"]
    assert request_fixture["dimension"] == "reporting_period"
    assert request_fixture["limit"] <= 100


def test_structured_dataset_response_fixtures_match_frozen_schema() -> None:
    validator = _build_validator("structured_dataset_response_v1.schema.json")
    response_fixture = _load_json("structured_dataset_response_v1.json")
    truncated_fixture = _load_json("structured_dataset_response_truncated_v1.json")

    for payload in (response_fixture, truncated_fixture):
        validator.validate(payload)

        assert payload["row_count"] == len(payload["rows"])
        assert "chart_type" not in payload
        assert "renderer" not in payload

        columns = {column["name"]: column for column in payload["columns"]}
        assert any(column["semantic_role"] == "time" for column in columns.values())
        assert any(column["semantic_role"] == "metric" for column in columns.values())

        for row in payload["rows"]:
            assert set(row).issubset(columns)

        assert all(
            not isinstance(value, (dict, list))
            for value in payload["provenance"].values()
        )

    assert response_fixture["truncated"] is False
    assert response_fixture["total_row_count"] == response_fixture["row_count"]

    assert truncated_fixture["truncated"] is True
    assert truncated_fixture["total_row_count"] > truncated_fixture["row_count"]
    assert truncated_fixture["warnings"]


def test_phase0_dataset_fixtures_embed_in_current_tool_result_envelope() -> None:
    response_fixture = _load_json("structured_dataset_response_v1.json")
    truncated_fixture = _load_json("structured_dataset_response_truncated_v1.json")

    success_envelope = ToolResultEnvelope(
        ok=True,
        tool_name="reporting.query_metric_series",
        summary=ToolResultSummary(
            message="Returned monthly income and expense totals.",
            item_count=response_fixture["row_count"],
            truncated=response_fixture["truncated"],
        ),
        data={"dataset": response_fixture},
        meta={
            "schema_version": response_fixture["schema_version"],
            "output_schema": "structured_dataset_v1",
        },
    )
    truncated_envelope = ToolResultEnvelope(
        ok=True,
        tool_name="reporting.query_metric_series",
        summary=ToolResultSummary(
            message="Returned truncated monthly income and expense totals.",
            item_count=truncated_fixture["row_count"],
            truncated=truncated_fixture["truncated"],
        ),
        data={"dataset": truncated_fixture},
        meta={
            "schema_version": truncated_fixture["schema_version"],
            "output_schema": "structured_dataset_v1",
        },
    )

    assert success_envelope.data["dataset"]["dataset_id"] == response_fixture["dataset_id"]
    assert truncated_envelope.summary.truncated is True


def test_phase0_error_catalog_and_error_fixture_are_consistent() -> None:
    catalog = _load_json("reporting_error_catalog_v1.json")
    error_fixture = _load_json("query_metric_series_error_v1.json")

    codes = {entry["code"] for entry in catalog["errors"]}

    assert catalog["schema_version"] == "1.0"
    assert codes == EXPECTED_ERROR_CODES
    assert catalog["tool_names"] == [
        "reporting.query_metric_series",
        "reporting.query_category_summary",
    ]

    envelope = ToolResultEnvelope.model_validate(error_fixture)

    assert envelope.ok is False
    assert len(envelope.errors) == 1
    assert envelope.errors[0].code in codes
    assert envelope.errors[0].code == "unsupported_metric"
