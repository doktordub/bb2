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


def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_capabilities_route_returns_frontend_safe_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_full.yaml")

    app = create_app(load_settings(env_file=None))

    with TestClient(app) as client:
        response = client.get("/capabilities", headers={"x-trace-id": "trace-cap-1234"})

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": "trace-cap-1234",
        "data": {
            "chat": {
                "enabled": True,
                "streaming_enabled": True,
                "max_message_chars": 20000,
            },
            "sessions": {
                "reset_enabled": True,
                "history_enabled": False,
                "list_enabled": False,
                "delete_enabled": False,
                "client_session_id_enabled": True,
            },
            "usecases": [
                {
                    "name": "routing_chat",
                    "display_name": "Routing Chat",
                    "description": "Routed chat use case.",
                    "strategy_type": "router",
                    "streaming_supported": True,
                    "memory_enabled": False,
                    "tools_enabled": True,
                },
                {
                    "name": "support_chat",
                    "display_name": "Support Chat",
                    "description": "Support chat use case.",
                    "strategy_type": "direct_agent",
                    "streaming_supported": True,
                    "memory_enabled": True,
                    "tools_enabled": True,
                },
            ],
            "agents": [
                {
                    "name": "analyst_agent",
                    "display_name": "Analyst Agent",
                    "type": "custom",
                    "streaming_supported": True,
                    "capabilities": ["answer", "memory_context", "tool_reasoning"],
                },
                {
                    "name": "support_agent",
                    "display_name": "Support Agent",
                    "type": "custom",
                    "streaming_supported": True,
                    "capabilities": ["answer", "memory_context", "tool_reasoning"],
                },
            ],
            "debug": {
                "trace_routes_enabled": False,
                "restart_enabled": False,
            },
            "tools": {
                "enabled": True,
                "configured": True,
                "streaming_supported": False,
                "total_tools": 2,
                "approval_required_tools": 0,
                "safety_levels": {
                    "read_only": 2,
                    "write": 0,
                    "destructive": 0,
                    "external_side_effect": 0,
                },
                "transport": "http",
                "discovery_enabled": True,
            },
            "memory": {
                "enabled": True,
                "configured": True,
                "provider": "memory_store",
                "search_available": True,
                "ingest_available": True,
            },
            "llm": {
                "enabled": True,
                "default_profile": "cloud_fast",
                "streaming_supported": True,
                "structured_output_supported": False,
            },
        },
        "metadata": {},
    }