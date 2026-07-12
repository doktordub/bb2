from __future__ import annotations

import json
from pathlib import Path


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = FRONTEND_ROOT.parent
SHARED_FIXTURE_DIR = WORKSPACE_ROOT / "backend" / "tests" / "fixtures" / "visualization"
FRONTEND_EDGE_FIXTURE_DIR = FRONTEND_ROOT / "tests" / "fixtures" / "visualization"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_frontend_phase0_uses_shared_backend_visualization_fixtures() -> None:
    artifact_path = SHARED_FIXTURE_DIR / "chart_artifact_v1.json"
    response_path = SHARED_FIXTURE_DIR / "chat_response_with_chart_v1.json"
    events_path = SHARED_FIXTURE_DIR / "sse_artifact_events_v1.jsonl"
    catalog_path = SHARED_FIXTURE_DIR / "golden_fixture_catalog_v1.json"

    assert artifact_path.is_file()
    assert response_path.is_file()
    assert events_path.is_file()
    assert catalog_path.is_file()

    artifact = _load_json(artifact_path)
    response = _load_json(response_path)
    events = _load_jsonl(events_path)
    catalog = _load_json(catalog_path)

    assert artifact["renderer"] == "echarts"
    assert artifact["spec_version"] == "1.0"
    assert response["data"]["artifacts"] == [artifact]
    assert [event["event"] for event in events] == [
        "response.started",
        "response.metadata",
        "response.delta",
        "artifact.started",
        "artifact.completed",
        "response.completed",
    ]
    assert {
        case["id"] for case in catalog["cases"]
    } >= {
        "bar_income_expense",
        "reference_mode_large_series",
        "missing_data",
        "expired_artifact",
    }


def test_frontend_phase0_edge_fixtures_cover_deferred_visualization_cases() -> None:
    unsupported = _load_json(FRONTEND_EDGE_FIXTURE_DIR / "unsupported_chart_artifact_v1.json")
    reference_mode = _load_json(
        FRONTEND_EDGE_FIXTURE_DIR / "reference_mode_artifact_provisional_v1.json"
    )
    expired_reference = _load_json(
        FRONTEND_EDGE_FIXTURE_DIR / "expired_reference_error_provisional_v1.json"
    )
    multi_artifact = _load_json(
        FRONTEND_EDGE_FIXTURE_DIR / "multi_artifact_chat_response_provisional_v1.json"
    )

    assert unsupported["chart_type"] == "sankey"
    assert unsupported["metadata"]["contract_status"] == "provisional"

    assert reference_mode["data_mode"] == "reference"
    assert reference_mode["data"] is None
    assert str(reference_mode["data_ref"]).startswith("/ui-api/artifacts/")
    assert reference_mode["metadata"]["contract_status"] == "provisional"

    assert expired_reference["status_code"] == 410
    assert expired_reference["error"]["code"] == "artifact_expired"

    assert len(multi_artifact["data"]["artifacts"]) == 2
    assert multi_artifact["metadata"]["artifact_delivery_mode"] == "inline"