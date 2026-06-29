from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.bootstrap import build_container
from app.config.loader import load_validated_config
from app.config.settings import load_settings
from app.config.view import ValidatedConfigurationView, get_agents_settings, get_orchestration_settings
from app.orchestration.registry import AgentRegistry
from app.orchestration.health import build_orchestration_health
from app.orchestration.runtime import build_strategy_registry


FIXTURES_DIR = Path("tests/fixtures/config")
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


def _load_config(override_name: str) -> ValidatedConfigurationView:
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / override_name,
        env={},
    )
    return ValidatedConfigurationView(parsed.model_dump(mode="python"))


def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_orchestration_health_reports_safe_registered_agent_readiness() -> None:
    config = _load_config("agents_general_assistant.yaml")
    health = build_orchestration_health(
        get_orchestration_settings(config),
        strategy_registry=build_strategy_registry(config),
        agent_registry=AgentRegistry.from_config(config),
        agent_settings=get_agents_settings(config),
    )

    assert len(health.agents) == 1
    assert health.agents[0].agent_name == "support_agent"
    assert health.agents[0].agent_type == "general_assistant"
    assert health.agents[0].status == "ok"
    assert health.agents[0].enabled is True
    assert health.agents[0].configured_llm_profile == "local_reasoning"
    assert health.agents[0].prompt_profile == "general_assistant_v1"
    assert health.agents[0].memory_required is False
    assert health.agents[0].tools_required is False
    assert health.agents[0].streaming_supported is True
    assert health.agents[0].metadata == {"registered": True}


@pytest.mark.asyncio
async def test_startup_config_summary_redacts_entrypoint_and_prompt_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "tests/fixtures/config/agents_tool_using.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())

    container = await build_container(load_settings(env_file=None))
    summary = container.config_summary["agents"]

    assert summary["enabled"] is True
    assert summary["configured_count"] == 1
    assert summary["enabled_count"] == 1
    assert summary["registered_count"] == 1
    assert summary["types"] == ["tool_using"]
    assert summary["streaming_supported"] is True
    assert summary["streaming_agent_count"] == 1
    assert summary["registered_agents"] == [
        {
            "agent_name": "support_agent",
            "agent_type": "tool_using",
            "status": "ok",
            "enabled": True,
            "configured_llm_profile": "local_reasoning",
            "prompt_profile": "tool_using_v1",
            "memory_required": False,
            "tools_required": False,
            "streaming_supported": True,
        }
    ]

    serialized = json.dumps(summary)
    assert "app.testing.fakes.fake_agent" not in serialized
    assert "FakeAgent" not in serialized
    assert "system_prompt" not in serialized
    assert "developer_prompt" not in serialized

    await container.close()