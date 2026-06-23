import re

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


GENERATED_TRACE_ID_PATTERN = re.compile(r"^trace_[0-9a-f]{32}$")


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


def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_health_route(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    monkeypatch.setenv("MCP_MAIN_URL", "https://mcp.example.local")
    monkeypatch.setenv("OPENAI_API_KEY", "top-secret-openai-key")
    monkeypatch.setenv("OPENAI_AUTHORIZATION", "Bearer extra-secret-token")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "local-secret-key")
    monkeypatch.setenv("MEMORY_STORE_DB_PATH", "./data/test-memory-store")

    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert GENERATED_TRACE_ID_PATTERN.fullmatch(response.headers["x-trace-id"])

        assert response.json() == {
            "status": "ok",
            "service": "pluggable-agentic-ai-backend",
            "version": "0.1.0",
            "environment": "local",
            "checks": {
                "settings": {"status": "ok"},
                "config": {
                    "status": "ok",
                    "configured": True,
                    "environment": "local",
                    "active_usecase": "support_chat",
                    "llm_profiles_count": 2,
                    "llm_providers": ["local_provider", "openai"],
                    "mcp_configured": True,
                    "workflow_state_provider": "sqlite",
                    "trace_provider": "sqlite",
                    "memory_provider": "memory_store",
                },
                "logging": {"status": "ok"},
                "observability": {
                    "status": "ok",
                    "trace_enabled": True,
                    "trace_payloads_enabled": True,
                    "trace_store_required": True,
                    "structured_logging": True,
                    "metrics_enabled": True,
                    "trace_store_configured": True,
                },
                "mcp": {"status": "not_checked", "configured": True},
                "llm": {"status": "not_checked", "configured": True},
                "memory": {"status": "not_checked", "configured": True},
                "workflow_state": {"status": "not_checked", "configured": True},
                "trace": {
                    "status": "ok",
                    "configured": True,
                    "provider": "sqlite",
                    "database_exists": True,
                },
            },
        }

        response_body = response.text
        assert "https://mcp.example.local" not in response_body
        assert "top-secret-openai-key" not in response_body
        assert "Bearer extra-secret-token" not in response_body
        assert "local-secret-key" not in response_body
