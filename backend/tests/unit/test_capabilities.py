import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.main import create_app


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
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


def test_capabilities_route(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)

    app = create_app(load_settings(env_file=None))
    client = TestClient(app)

    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "service": "pluggable-agentic-ai-backend",
        "capabilities": {
            "chat": False,
            "streaming": False,
            "session_reset": False,
            "mcp_tools": False,
            "memory": False,
            "llm_profiles": False,
            "trace": False,
        },
    }