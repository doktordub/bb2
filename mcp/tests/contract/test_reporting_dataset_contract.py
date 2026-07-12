from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

from app.bootstrap import bootstrap
from app.tools_base.validation import load_manifest, load_tool_config
from tools.reporting.plugin import create_plugin


REPORTING_TOOL_DIR = Path(__file__).resolve().parents[2] / "tools" / "reporting"
VISUALIZATION_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "visualization"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((VISUALIZATION_FIXTURES_DIR / name).read_text(encoding="utf-8"))


async def test_reporting_tool_success_shape_matches_backend_visualization_fixture() -> None:
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=load_tool_config(REPORTING_TOOL_DIR / "config.yaml"),
    )

    server = FastMCP("reporting-contract-shape")
    create_plugin(context).register(server)
    result = await server.call_tool(
        "reporting.query_metric_series",
        {
            "metric_names": ["income", "expense"],
            "dimension": "reporting_period",
            "granularity": "month",
            "limit": 6,
        },
    )

    fixture = _load_json("structured_dataset_response_v1.json")
    dataset = result.structured_content["data"]["dataset"]

    assert result.structured_content["ok"] is True
    assert result.structured_content["meta"]["output_schema"] == "structured_dataset_v1"
    assert set(dataset) == set(fixture)
    assert [column["name"] for column in dataset["columns"]] == [
        column["name"] for column in fixture["columns"]
    ]
    assert dataset["rows"] == fixture["rows"]
    assert dataset["row_count"] == fixture["row_count"]
    assert dataset["total_row_count"] == fixture["total_row_count"]
    assert dataset["truncated"] == fixture["truncated"]
    assert dataset["time_range"] == fixture["time_range"]
    assert set(dataset["provenance"]).issuperset(set(fixture["provenance"]))


async def test_reporting_tool_truncated_shape_matches_backend_visualization_fixture() -> None:
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=load_tool_config(REPORTING_TOOL_DIR / "config.yaml"),
    )

    server = FastMCP("reporting-contract-truncated-shape")
    create_plugin(context).register(server)
    result = await server.call_tool(
        "reporting.query_metric_series",
        {
            "metric_names": ["income", "expense"],
            "dimension": "reporting_period",
            "granularity": "month",
            "limit": 3,
        },
    )

    fixture = _load_json("structured_dataset_response_truncated_v1.json")
    dataset = result.structured_content["data"]["dataset"]

    assert result.structured_content["ok"] is True
    assert set(dataset) == set(fixture)
    assert dataset["rows"] == fixture["rows"]
    assert dataset["row_count"] == fixture["row_count"]
    assert dataset["total_row_count"] == fixture["total_row_count"]
    assert dataset["truncated"] == fixture["truncated"]
    assert dataset["time_range"] == fixture["time_range"]
    assert dataset["warnings"]