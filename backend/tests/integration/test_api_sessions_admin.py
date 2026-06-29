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
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "tests/fixtures/config/session_management_enabled.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def test_api_sessions_admin_routes_work_against_real_sqlite_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        first = client.post("/chat", json={"message": "hello", "session_id": "session_admin_1"})
        second = client.post("/chat", json={"message": "hi", "session_id": "session_admin_2"})

        assert first.status_code == 200
        assert second.status_code == 200

        listed = client.get("/sessions?limit=10", headers={"x-trace-id": "trace-admin-list"})

        assert listed.status_code == 200
        payload = listed.json()
        assert payload["trace_id"] == "trace-admin-list"
        assert payload["data"]["limit"] == 10
        assert {item["session_id"] for item in payload["data"]["sessions"]} == {
            "session_admin_1",
            "session_admin_2",
        }

        deleted = client.delete("/sessions/session_admin_1", headers={"x-trace-id": "trace-admin-delete"})

        assert deleted.status_code == 200
        assert deleted.json() == {
            "schema_version": "1.0",
            "trace_id": "trace-admin-delete",
            "session_id": "session_admin_1",
            "data": {
                "deleted": True,
                "message": "Session workflow state was deleted.",
            },
            "metadata": {"deleted": True},
        }

        listed_after = client.get("/sessions?limit=10")
        assert listed_after.status_code == 200
        assert [item["session_id"] for item in listed_after.json()["data"]["sessions"]] == [
            "session_admin_2"
        ]