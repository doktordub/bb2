from __future__ import annotations

import pytest

from app.agents.registry import AgentRegistry, build_agent_registry
from app.config.view import get_agents_settings
from app.contracts.errors import ConfigurationError
from app.testing.fakes import FakeAgent, FakeConfigurationView


def build_legacy_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "description": "Legacy support agent.",
                    "llm_profile": "local_reasoning",
                }
            }
        }
    )


def test_build_agent_registry_supports_legacy_agent_shape() -> None:
    config = build_legacy_config()
    settings = get_agents_settings(config)

    registry = build_agent_registry(config, settings=settings)

    assert registry.contains("support_agent") is True
    agent = registry.resolve("support_agent")
    assert isinstance(agent, FakeAgent)
    assert registry.require("support_agent") is agent
    assert registry.get("support_agent") is agent
    assert registry.get("missing") is None

    descriptors = registry.list()
    assert len(descriptors) == 1
    assert descriptors[0].name == "support_agent"
    assert descriptors[0].type == "custom"
    assert descriptors[0].llm_profile == "local_reasoning"
    assert descriptors[0].capabilities.stream is True

    assert registry.startup_summary(settings=settings) == {
        "enabled": True,
        "configured_count": 1,
        "enabled_count": 1,
        "registered_count": 1,
        "types": ["custom"],
        "streaming_supported": True,
        "streaming_agent_count": 1,
    }


def test_agent_registry_rejects_duplicate_registration() -> None:
    registry = AgentRegistry()

    registry.register(FakeAgent(name="support_agent"))

    with pytest.raises(
        ConfigurationError,
        match="Duplicate agent registration for 'support_agent'",
    ):
        registry.register(FakeAgent(name="support_agent"))


def test_agent_registry_raises_for_missing_agent() -> None:
    registry = AgentRegistry()

    with pytest.raises(Exception, match="Configured agent 'missing_agent' is not available"):
        registry.require("missing_agent")