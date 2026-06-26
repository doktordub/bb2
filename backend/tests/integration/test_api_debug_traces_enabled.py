from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


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


def build_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/api_debug_traces_enabled.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_debug_trace_routes_expose_redacted_real_trace_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        source = client.get("/health", headers={"x-trace-id": "trace-debug-int-0001"})
        assert source.status_code == 200

        search = client.get("/debug/traces", params={"limit": 10})

    assert search.status_code == 200
    search_payload = search.json()
    assert search_payload["schema_version"] == "1.0"
    assert search_payload["metadata"]["limit"] == 10
    assert search_payload["metadata"]["result_count"] >= 1
    trace_ids = [item["trace_id"] for item in search_payload["data"]["traces"]]
    assert "trace-debug-int-0001" in trace_ids

    with TestClient(app) as client:
        read = client.get("/debug/traces/trace-debug-int-0001", params={"limit": 5})

    assert read.status_code == 200
    read_payload = read.json()
    assert read_payload["schema_version"] == "1.0"
    assert read_payload["data"]["summary"]["trace_id"] == "trace-debug-int-0001"
    assert read_payload["metadata"]["limit"] == 5
    assert read_payload["metadata"]["returned_events"] == len(read_payload["data"]["events"])
    assert read_payload["metadata"]["total_events"] == read_payload["data"]["summary"]["event_count"]
    assert read_payload["metadata"]["truncated"] == (
        read_payload["data"]["summary"]["event_count"] > len(read_payload["data"]["events"])
    )
    assert all("payload" in event for event in read_payload["data"]["events"])