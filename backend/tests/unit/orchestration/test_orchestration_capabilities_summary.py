from __future__ import annotations

from pathlib import Path

from app.config.loader import load_validated_config
from app.config.view import ValidatedConfigurationView, get_agents_settings, get_orchestration_settings
from app.orchestration.registry import AgentRegistry
from app.orchestration.capabilities import build_orchestration_capabilities
from app.orchestration.runtime import build_strategy_registry
from app.testing.fakes import FakeConfigurationView


FIXTURES_DIR = Path("tests/fixtures/config")


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "support_chat"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["support_chat"],
                        "llm_profile": "local_reasoning",
                        "memory_enabled": True,
                        "tools_enabled": True,
                        "description": "Run the default configured agent.",
                    }
                },
                "usecases": {
                    "support_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "llm_profile": "local_reasoning",
                        "display_name": "Support Chat",
                        "description": "Support chat use case.",
                        "allowed_agents": ["support_agent"],
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 8,
                        },
                        "tools": {
                            "enabled": True,
                            "allowed_tools": ["documents.search"],
                        },
                    }
                },
            },
        }
    )


def test_build_orchestration_capabilities_returns_safe_usecase_descriptors() -> None:
    config = build_config()
    capabilities = build_orchestration_capabilities(
        get_orchestration_settings(config),
        strategy_registry=build_strategy_registry(config),
    )

    assert capabilities.enabled is True
    assert capabilities.default_strategy == "direct_agent"
    assert capabilities.fallback_strategy == "direct_agent"
    assert capabilities.metadata == {
        "registered_agent_count": 0,
        "registered_strategy_count": 1,
        "strategy_types": ["direct_agent"],
    }
    assert [descriptor.name for descriptor in capabilities.strategies] == ["direct_agent"]
    assert capabilities.strategies[0].type == "direct_agent"
    assert capabilities.strategies[0].streaming_supported is True

    usecase = capabilities.usecases[0]
    assert usecase.name == "support_chat"
    assert usecase.display_name == "Support Chat"
    assert usecase.description == "Support chat use case."
    assert usecase.strategy == "direct_agent"
    assert usecase.strategy_type == "direct_agent"
    assert usecase.streaming_supported is True
    assert usecase.agent == "support_agent"
    assert usecase.llm_profile == "local_reasoning"
    assert usecase.memory_enabled is True
    assert usecase.tools_enabled is True


def test_build_orchestration_capabilities_includes_safe_agent_descriptors() -> None:
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / "agents_general_assistant.yaml",
        env={},
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    capabilities = build_orchestration_capabilities(
        get_orchestration_settings(config),
        strategy_registry=build_strategy_registry(config),
        agent_registry=AgentRegistry.from_config(config),
        agent_settings=get_agents_settings(config),
    )

    assert capabilities.metadata["registered_agent_count"] == 1
    assert len(capabilities.agents) == 1
    assert capabilities.agents[0].name == "support_agent"
    assert capabilities.agents[0].display_name == "Support Assistant"
    assert capabilities.agents[0].type == "general_assistant"
    assert capabilities.agents[0].streaming_supported is True
    assert capabilities.agents[0].capabilities == ("answer",)