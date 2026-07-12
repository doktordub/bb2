from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.visualization.models import (
    ChartArtifact,
    ChartArtifactEnvelope,
    ChartContextSummary,
    ContextContribution,
)


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"


def _load_json_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_chart_artifact_model_roundtrips_v1_fixture() -> None:
    payload = _load_json_fixture("chart_artifact_v1.json")

    artifact = ChartArtifact.model_validate(payload)

    assert artifact.model_dump(mode="json") == payload


def test_chart_context_summary_model_roundtrips_v1_fixture() -> None:
    payload = _load_json_fixture("chart_context_summary_v1.json")

    summary = ChartContextSummary.model_validate(payload)

    assert summary.model_dump(mode="json") == payload


def test_chart_context_summary_rejects_row_level_dataset_field() -> None:
    payload = _load_json_fixture("chart_context_summary_v1.json")
    payload["data"] = [{"month": "Jan", "income": 5200, "expense": 4100}]

    with pytest.raises(ValidationError):
        ChartContextSummary.model_validate(payload)


def test_chart_artifact_envelope_and_context_contribution_serialize_deterministically() -> None:
    artifact = ChartArtifact.model_validate(_load_json_fixture("chart_artifact_v1.json"))
    summary = ChartContextSummary.model_validate(_load_json_fixture("chart_context_summary_v1.json"))

    envelope = ChartArtifactEnvelope(artifact=artifact, context_summary=summary)
    contribution = ContextContribution(
        contribution_id="ctx_chart_income_expense_last_6_months",
        kind="chart_summary",
        content=summary.model_dump(mode="python"),
        token_estimate=summary.token_estimate or 0,
        source_artifact_id=summary.artifact_id,
    )

    assert envelope.model_dump(mode="json") == {
        "artifact": artifact.model_dump(mode="json"),
        "context_summary": summary.model_dump(mode="json"),
    }
    assert contribution.model_dump(mode="json") == {
        "contribution_id": "ctx_chart_income_expense_last_6_months",
        "kind": "chart_summary",
        "content": summary.model_dump(mode="json"),
        "token_estimate": 148,
        "source_artifact_id": "chart_income_expense_last_6_months",
        "include_in_next_prompt": True,
    }