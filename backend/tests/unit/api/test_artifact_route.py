from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app
from app.visualization.artifact_store import build_visualization_artifact_scope
from app.visualization.models import ChartArtifact, ChartContextSummary


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
    "APP_CONFIG_OVERRIDE_PATH",
    "APP_DATA_DIR",
    "APP_CONFIG_STRICT",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_RELOAD",
    "LOG_LEVEL",
    "LOG_JSON",
    "MCP_MAIN_URL",
    "LLM_LOCAL_QWEN_BASE_URL",
    "LLM_LOCAL_QWEN_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "MEMORY_STORE_CONFIG",
    "SQLITE_WORKFLOW_STATE_URL",
    "SQLITE_TRACE_URL",
]


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path, *, retrieval_enabled: bool) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    if retrieval_enabled:
        monkeypatch.setenv(
            "APP_CONFIG_OVERRIDE_PATH",
            "tests/fixtures/config/visualization_public_artifacts_enabled.yaml",
        )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_artifact_route_is_not_registered_when_public_retrieval_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path, retrieval_enabled=False)
    with TestClient(app):
        paths = {route.path for route in app.routes}

    assert "/artifacts/{artifact_id}" not in paths


def test_artifact_route_returns_session_scoped_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path, retrieval_enabled=True)

    with TestClient(app) as client:
        container = app.state.container
        assert container.visualization_artifact_store is not None

        scope = build_visualization_artifact_scope(
            session_id="session_artifact_route_1",
            user_id="local_user",
            scope=None,
        )
        artifact = ChartArtifact(
            artifact_id="chart_api_001",
            chart_type="bar",
            title="Revenue by Month",
            description="Monthly revenue totals.",
            renderer="echarts",
            spec_version="1.0",
            data_mode="inline",
            data=[{"month": "Jan", "revenue": 1200}, {"month": "Feb", "revenue": 1450}],
            data_ref=None,
            encoding={"x": "month", "y": ["revenue"]},
            metadata={"source": "workflow_state"},
        )
        summary = ChartContextSummary(
            artifact_id=artifact.artifact_id,
            chart_type=artifact.chart_type,
            title=artifact.title,
            description=artifact.description,
            renderer=artifact.renderer,
            data_source="workflow_state",
            x_field="month",
            y_fields=["revenue"],
            row_count=2,
            series_count=1,
            category_count=2,
            summary_text="Revenue rises from 1200 in Jan to 1450 in Feb.",
            key_insights=["Revenue increased month over month."],
            data_ref="artifact://session_artifact_route_1/chart_api_001",
        )
        asyncio.run(
            container.visualization_artifact_store.save_artifact(
                scope=scope,
                artifact=artifact,
                context_summary=summary,
                data=artifact.data,
            )
        )

        response = client.get(
            "/artifacts/chart_api_001",
            headers={
                "x-trace-id": "trace-artifact-route-0001",
                "x-session-id": "session_artifact_route_1",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-artifact-route-0001"
    assert response.headers["x-session-id"] == "session_artifact_route_1"
    assert response.headers["cache-control"].startswith("private, max-age=")
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": "trace-artifact-route-0001",
        "session_id": "session_artifact_route_1",
        "data": {
            "artifact_id": "chart_api_001",
            "type": "chart",
            "chart_type": "bar",
            "title": "Revenue by Month",
            "description": "Monthly revenue totals.",
            "renderer": "echarts",
            "spec_version": "1.0",
            "data_mode": "inline",
            "data": [
                {"month": "Jan", "revenue": 1200},
                {"month": "Feb", "revenue": 1450},
            ],
            "data_ref": None,
            "encoding": {"x": "month", "y": ["revenue"]},
            "options": {},
            "warnings": [],
            "metadata": {"source": "workflow_state"},
        },
        "metadata": {
            "return_type": "artifact",
            "field_count": 0,
        },
    }


def test_artifact_route_denies_wrong_session_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path, retrieval_enabled=True)

    with TestClient(app) as client:
        container = app.state.container
        assert container.visualization_artifact_store is not None

        scope = build_visualization_artifact_scope(
            session_id="session_artifact_route_1",
            user_id="local_user",
            scope=None,
        )
        artifact = ChartArtifact(
            artifact_id="chart_api_002",
            chart_type="bar",
            title="Revenue by Month",
            renderer="echarts",
            spec_version="1.0",
            data_mode="inline",
            data=[{"month": "Jan", "revenue": 1200}],
            data_ref=None,
            encoding={"x": "month", "y": ["revenue"]},
            metadata={"source": "workflow_state"},
        )
        summary = ChartContextSummary(
            artifact_id=artifact.artifact_id,
            chart_type=artifact.chart_type,
            title=artifact.title,
            renderer=artifact.renderer,
            data_source="workflow_state",
            x_field="month",
            y_fields=["revenue"],
            row_count=1,
            series_count=1,
            summary_text="Revenue is 1200 in Jan.",
            data_ref="artifact://session_artifact_route_1/chart_api_002",
        )
        asyncio.run(
            container.visualization_artifact_store.save_artifact(
                scope=scope,
                artifact=artifact,
                context_summary=summary,
                data=artifact.data,
            )
        )

        response = client.get(
            "/artifacts/chart_api_002",
            headers={
                "x-trace-id": "trace-artifact-route-0002",
                "x-session-id": "session_other_scope",
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "artifact_not_found"


def test_artifact_route_materializes_reference_artifacts_into_inline_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path, retrieval_enabled=True)

    with TestClient(app) as client:
        container = app.state.container
        assert container.visualization_artifact_store is not None

        scope = build_visualization_artifact_scope(
            session_id="session_artifact_route_ref",
            user_id="local_user",
            scope=None,
        )
        artifact = ChartArtifact(
            artifact_id="chart_api_ref_001",
            chart_type="bar",
            title="Revenue by Month",
            description="Monthly revenue totals.",
            renderer="echarts",
            spec_version="1.0",
            data_mode="reference",
            data=None,
            data_ref="artifact://session_artifact_route_ref/chart_api_ref_001",
            encoding={"x": "month", "y": ["revenue"]},
            metadata={"source": "workflow_state"},
        )
        summary = ChartContextSummary(
            artifact_id=artifact.artifact_id,
            chart_type=artifact.chart_type,
            title=artifact.title,
            description=artifact.description,
            renderer=artifact.renderer,
            data_source="workflow_state",
            x_field="month",
            y_fields=["revenue"],
            row_count=2,
            series_count=1,
            category_count=2,
            summary_text="Revenue rises from 1200 in Jan to 1450 in Feb.",
            key_insights=["Revenue increased month over month."],
            data_ref="artifact://session_artifact_route_ref/chart_api_ref_001",
        )
        rows = [{"month": "Jan", "revenue": 1200}, {"month": "Feb", "revenue": 1450}]
        asyncio.run(
            container.visualization_artifact_store.save_artifact(
                scope=scope,
                artifact=artifact,
                context_summary=summary,
                data=rows,
            )
        )

        response = client.get(
            "/artifacts/chart_api_ref_001",
            headers={
                "x-trace-id": "trace-artifact-route-ref-0001",
                "x-session-id": "session_artifact_route_ref",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["artifact_id"] == "chart_api_ref_001"
    assert payload["data"]["data_mode"] == "inline"
    assert payload["data"]["data_ref"] is None
    assert payload["data"]["data"] == rows