import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from app.contracts.health import HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_NOT_CONFIGURED, HEALTH_OK
from app.config.settings import load_settings
from app.main import create_app
from app.observability.health import HealthCheckResult
from app.persistence.health import (
    PersistenceHealthComponent,
    evaluate_persistence_bundle,
    evaluate_persistence_component,
)


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
        asyncio.run(
            app.state.container.workflow_state.save(
                "session-1",
                {
                    "conversation": {
                        "messages": [
                            {
                                "role": "user",
                                "content": "health route should stay redacted",
                            }
                        ]
                    },
                    "workflow": {"current_step": "diagnostic_check"},
                },
            )
        )
        response = client.get("/health")

        assert response.status_code == 200
        assert GENERATED_TRACE_ID_PATTERN.fullmatch(response.headers["x-trace-id"])
        payload = response.json()

        assert payload["status"] == "ok"
        assert payload["trace_id"] == response.headers["x-trace-id"]
        assert payload["service"] == "pluggable-agentic-ai-backend"
        assert payload["version"] == "0.1.0"
        assert payload["environment"] == "local"
        assert payload["backend"] == {
            "configured": True,
            "service": "pluggable-agentic-ai-backend",
            "version": "0.1.0",
            "environment": "local",
        }
        assert payload["api"] == {
            "configured": True,
            "docs_enabled": True,
            "streaming_enabled": True,
        }
        assert payload["checks"] == {
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
            "persistence": {
                "status": "ok",
                "configured": True,
                "required_components": 2,
                "optional_components": 1,
                "components": {
                    "workflow_state": "ok",
                    "trace": "ok",
                    "memory": "ok",
                },
            },
            "memory": {
                "status": "ok",
                "configured": True,
                "provider": "memory_store",
                "required": False,
                "config_path_configured": False,
                "database_path_configured": True,
                "service_initialized": False,
                "dependency_available": True,
            },
            "workflow_state": {
                "status": "ok",
                "configured": True,
                "provider": "sqlite",
                "required": True,
                "database_exists": True,
                "schema_initialized": True,
                "schema_version": 2,
                "journal_mode": "wal",
                "synchronous": "normal",
            },
            "trace": {
                "status": "ok",
                "configured": True,
                "provider": "sqlite",
                "required": True,
                "database_exists": True,
                "journal_mode": "wal",
                "synchronous": "normal",
                "retention_enabled": False,
                "schema_initialized": True,
                "schema_version": 2,
            },
        }
        assert payload["memory"] == payload["checks"]["memory"]
        assert payload["workflow_state"] == payload["checks"]["workflow_state"]
        assert payload["trace"] == payload["checks"]["trace"]
        assert payload["llm"] == payload["checks"]["llm"]
        assert payload["mcp"] == payload["checks"]["mcp"]

        response_body = response.text
        assert "https://mcp.example.local" not in response_body
        assert "top-secret-openai-key" not in response_body
        assert "Bearer extra-secret-token" not in response_body
        assert "local-secret-key" not in response_body
        assert "session-1" not in response_body
        assert "health route should stay redacted" not in response_body
        assert str(tmp_path) not in response_body


class _FakeHealthComponent:
    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = payload or {"status": "ok", "provider": "fake"}
        self._error = error

    async def health(self) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        return dict(self._payload)


@pytest.mark.asyncio
async def test_optional_persistence_component_failure_degrades_health() -> None:
    component = PersistenceHealthComponent(
        name="memory",
        provider="memory_store",
        required=False,
        component=_FakeHealthComponent(error=RuntimeError("boom")),
    )

    result = await evaluate_persistence_component(component)

    assert result == HealthCheckResult(
        status=HEALTH_DEGRADED,
        details={
            "configured": True,
            "provider": "memory_store",
            "required": False,
            "error_type": "RuntimeError",
        },
    )


@pytest.mark.asyncio
async def test_required_persistence_component_failure_fails_health() -> None:
    component = PersistenceHealthComponent(
        name="trace",
        provider="sqlite",
        required=True,
        component=_FakeHealthComponent(error=RuntimeError("boom")),
    )

    result = await evaluate_persistence_component(component)

    assert result == HealthCheckResult(
        status=HEALTH_FAILED,
        details={
            "configured": True,
            "provider": "sqlite",
            "required": True,
            "error_type": "RuntimeError",
        },
    )


@pytest.mark.asyncio
async def test_persistence_bundle_health_stays_ok_with_optional_not_configured_component() -> None:
    components = {
        "workflow_state": PersistenceHealthComponent(
            name="workflow_state",
            provider="sqlite",
            required=True,
            component=_FakeHealthComponent({"status": HEALTH_OK, "provider": "sqlite"}),
        ),
        "trace": PersistenceHealthComponent(
            name="trace",
            provider="sqlite",
            required=True,
            component=_FakeHealthComponent({"status": HEALTH_OK, "provider": "sqlite"}),
        ),
        "memory": PersistenceHealthComponent(
            name="memory",
            provider="memory_store",
            required=False,
            component=_FakeHealthComponent(
                {"status": HEALTH_NOT_CONFIGURED, "provider": "memory_store", "configured": False}
            ),
        ),
    }

    result = await evaluate_persistence_bundle(components)

    assert result == HealthCheckResult(
        status=HEALTH_OK,
        details={
            "configured": True,
            "required_components": 2,
            "optional_components": 1,
            "components": {
                "workflow_state": HEALTH_OK,
                "trace": HEALTH_OK,
                "memory": HEALTH_NOT_CONFIGURED,
            },
        },
    )
