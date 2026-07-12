from __future__ import annotations

import json
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"


def _load_json_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_jsonl_fixture(name: str) -> list[dict[str, object]]:
    path = FIXTURE_DIR / name
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_chart_artifact_fixture_matches_inline_v1_contract() -> None:
    artifact = _load_json_fixture("chart_artifact_v1.json")

    assert artifact["artifact_id"] == "chart_income_expense_last_6_months"
    assert artifact["type"] == "chart"
    assert artifact["chart_type"] == "grouped_bar"
    assert artifact["renderer"] == "echarts"
    assert artifact["spec_version"] == "1.0"
    assert artifact["data_mode"] == "inline"
    assert artifact["data_ref"] is None
    assert isinstance(artifact["data"], list)
    assert len(artifact["data"]) == 6
    assert artifact["warnings"] == []


def test_chart_context_summary_fixture_is_bounded_and_references_artifact() -> None:
    artifact = _load_json_fixture("chart_artifact_v1.json")
    summary = _load_json_fixture("chart_context_summary_v1.json")

    assert summary["artifact_id"] == artifact["artifact_id"]
    assert summary["renderer"] == artifact["renderer"]
    assert summary["row_count"] == len(artifact["data"])
    assert summary["series_count"] == 2
    assert summary["warnings"] == []
    assert summary["data_ref"] == "artifact://session_vis_001/chart_income_expense_last_6_months"
    assert "data" not in summary


def test_chat_response_fixture_extends_current_api_envelope_additively() -> None:
    artifact = _load_json_fixture("chart_artifact_v1.json")
    response = _load_json_fixture("chat_response_with_chart_v1.json")

    assert response["schema_version"] == "1.0"
    assert response["trace_id"] == "trace_vis_001"
    assert response["session_id"] == "session_vis_001"
    assert response["data"]["artifacts"] == [artifact]
    assert response["metadata"]["context_summary_added"] is True


def test_sse_fixture_preserves_response_prefix_and_adds_artifact_event() -> None:
    artifact = _load_json_fixture("chart_artifact_v1.json")
    events = _load_jsonl_fixture("sse_artifact_events_v1.jsonl")

    assert [event["event"] for event in events] == [
        "response.started",
        "response.metadata",
        "response.delta",
        "artifact.started",
        "artifact.completed",
        "response.completed",
    ]
    assert all(not str(event["event"]).startswith("message.") for event in events)
    started_event = next(event for event in events if event["event"] == "artifact.started")
    completed_event = next(event for event in events if event["event"] == "artifact.completed")
    assert started_event["data"]["artifact_id"] == artifact["artifact_id"]
    assert completed_event["data"]["artifact"] == artifact