from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools_base.dataset_models import (
    MetricSeriesQuery,
    StructuredDatasetResponse,
    build_metric_series_query_summary,
    export_metric_series_query_json_schema,
    export_structured_dataset_response_json_schema,
    generate_dataset_id,
)
from app.tools_base.dataset_validation import (
    DatasetTransportLimits,
    normalize_structured_dataset_result,
    validate_structured_dataset_response,
)


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "visualization"


def _load_json(name: str) -> object:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_phase1_schema_export_matches_frozen_phase0_contract() -> None:
    assert export_metric_series_query_json_schema() == _load_json(
        "query_metric_series_request_v1.schema.json"
    )
    assert export_structured_dataset_response_json_schema() == _load_json(
        "structured_dataset_response_v1.schema.json"
    )


def test_phase1_models_accept_frozen_fixtures_and_build_safe_summary() -> None:
    request = MetricSeriesQuery.model_validate(_load_json("query_metric_series_request_v1.json"))
    dataset = validate_structured_dataset_response(_load_json("structured_dataset_response_v1.json"))

    summary = build_metric_series_query_summary(request, row_count=dataset.row_count)

    assert request.dimension == "reporting_period"
    assert summary.startswith("sum aggregation for metrics income, expense")
    assert "core" not in summary
    assert dataset.dataset_id == generate_dataset_id(
        "reporting",
        "metric_series",
        "monthly_income_expense",
        version_tag="v1",
    )


def test_phase1_normalizes_dataset_into_current_tool_result_envelope() -> None:
    envelope = normalize_structured_dataset_result(
        tool_name="reporting.query_metric_series",
        dataset=_load_json("structured_dataset_response_truncated_v1.json"),
    )

    assert envelope.summary.truncated is True
    assert envelope.meta == {
        "schema_version": "1.0",
        "output_schema": "structured_dataset_v1",
        "dataset_id": "reporting.metric_series.monthly_income_expense.v1",
    }
    assert envelope.data["dataset"]["row_count"] == 3


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["columns"].append(
                {
                    "name": "income",
                    "data_type": "number",
                    "nullable": False,
                    "semantic_role": "metric",
                    "unit": "USD",
                }
            ),
            "duplicate names",
        ),
        (
            lambda payload: payload["rows"][0].update({"unexpected": 1}),
            "unknown fields",
        ),
        (
            lambda payload: payload["rows"][0].update({"reporting_period": "2026-13-01"}),
            "valid ISO date string",
        ),
        (
            lambda payload: payload["rows"][0].update({"income": "not-a-number"}),
            "must be numeric",
        ),
        (
            lambda payload: payload["rows"][0].update({"income": float("nan")}),
            "non-finite numeric values",
        ),
        (
            lambda payload: payload.__setitem__("row_count", 99),
            "row_count must match",
        ),
        (
            lambda payload: payload["provenance"].update({"api_key": "secret"}),
            "secret-like",
        ),
        (
            lambda payload: payload["provenance"].update(
                {"token_preview": "Bearer abcdefghijklmnopqrstuvwxyz123456"}
            ),
            "secret-like",
        ),
    ],
)
def test_phase1_rejects_invalid_dataset_shapes(mutator, message: str) -> None:
    payload = _load_json("structured_dataset_response_v1.json")
    assert isinstance(payload, dict)
    mutator(payload)

    with pytest.raises(ValidationError, match=message):
        StructuredDatasetResponse.model_validate(payload)


def test_phase1_rejects_invalid_query_date_ranges() -> None:
    with pytest.raises(ValidationError, match="start_date"):
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            start_date="2026-07-01",
            end_date="2026-06-30",
            aggregation="sum",
            granularity="month",
            sort="asc",
            limit=10,
        )


def test_phase1_enforces_metadata_and_result_byte_limits() -> None:
    payload = _load_json("structured_dataset_response_v1.json")
    assert isinstance(payload, dict)

    with pytest.raises(ValueError, match="max_metadata_bytes"):
        validate_structured_dataset_response(
            payload,
            limits=DatasetTransportLimits(max_metadata_bytes=64),
        )

    with pytest.raises(ValueError, match="max_result_bytes"):
        normalize_structured_dataset_result(
            tool_name="reporting.query_metric_series",
            dataset=payload,
            limits=DatasetTransportLimits(max_result_bytes=256),
        )