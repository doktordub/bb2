from __future__ import annotations

import pytest

from app.agents.factory import AgentFactory
from app.agents.plugins.general_assistant import GeneralAssistantAgent
from app.config.view import get_agents_settings
from app.contracts.errors import ConfigurationError
from app.testing.fakes import FakeAgent, FakeConfigurationView


def build_canonical_config(*, include_entrypoint: bool = False) -> FakeConfigurationView:
    plugin: dict[str, object] = {
        "enabled": True,
        "type": "general_assistant",
        "display_name": "Support Agent",
        "description": "Configured support agent.",
        "llm_profile": "local_reasoning",
        "prompt_profile": "general_assistant_v1",
        "capabilities": {
            "answer": True,
            "review": False,
            "stream": True,
            "memory_read": False,
            "memory_write": False,
            "memory_candidate_extract": False,
            "tool_intents": True,
            "tool_execute": False,
            "self_managed_memory": False,
            "self_managed_tools": False,
        },
        "allowed_tool_intents": ["documents_search"],
        "allowed_memory_scopes": ["project"],
        "prompts": {
            "system_prompt": "You are the configured support system prompt.",
            "developer_prompt": "Prefer concise answers.",
        },
        "metadata": {"tier": "primary"},
    }
    if include_entrypoint:
        plugin["module"] = "app.testing.fakes.fake_agent"
        plugin["class_name"] = "FakeAgent"

    return FakeConfigurationView(
        {
            "agents": {
                "defaults": {
                    "enabled": True,
                    "stream_llm_deltas": True,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": False,
                    "allow_self_managed_tools": False,
                    "allow_self_managed_memory": False,
                    "allow_memory_write": False,
                },
                "plugins": {"support_agent": plugin},
            }
        }
    )


def test_agent_factory_builds_builtin_general_assistant() -> None:
    config = build_canonical_config()
    settings = get_agents_settings(config)
    factory = AgentFactory(settings=settings)

    agent = factory.build(settings.plugins["support_agent"])

    assert isinstance(agent, GeneralAssistantAgent)
    assert agent.name == "support_agent"
    assert agent.type == "general_assistant"
    assert agent.description == "Configured support agent."
    assert agent.display_name == "Support Agent"
    assert agent.default_llm_profile == "local_reasoning"
    assert agent.prompt_profile == "general_assistant_v1"
    assert agent.system_prompt_override == "You are the configured support system prompt."
    assert agent.developer_prompt == "Prefer concise answers."
    assert agent.component == "agent.support_agent"
    assert agent.stream_llm_deltas is True
    assert agent.limits.max_output_chars == 12000
    assert agent.metadata["tier"] == "primary"
    assert agent.metadata["entrypoint_mode"] == "builtin"
    assert agent.metadata["stream_llm_deltas"] is True
    assert agent.metadata["allowed_tool_intent_count"] == 1
    assert agent.metadata["allowed_memory_scope_count"] == 1
    assert agent.metadata["built_in"] is True
    assert agent.metadata["mode"] == "direct_answer_only"

    descriptor = agent.descriptor()
    assert descriptor.name == "support_agent"
    assert descriptor.type == "general_assistant"
    assert descriptor.llm_profile == "local_reasoning"
    assert descriptor.capabilities.answer is True
    assert descriptor.capabilities.stream is True
    assert descriptor.capabilities.tool_intents is True


def test_agent_factory_builds_configured_agent_from_explicit_entrypoint() -> None:
    config = build_canonical_config(include_entrypoint=True)
    settings = get_agents_settings(config)
    factory = AgentFactory(settings=settings)

    agent = factory.build(settings.plugins["support_agent"])

    assert isinstance(agent, FakeAgent)
    assert agent.name == "support_agent"
    assert agent.type == "general_assistant"
    assert agent.description == "Configured support agent."
    assert agent.display_name == "Support Agent"
    assert agent.default_llm_profile == "local_reasoning"
    assert agent.prompt_profile == "general_assistant_v1"
    assert agent.system_prompt_override == "You are the configured support system prompt."
    assert agent.developer_prompt == "Prefer concise answers."
    assert agent.component == "agent.support_agent"
    assert agent.capabilities == ["answer", "stream", "tool_intents"]
    assert agent.metadata == {
        "tier": "primary",
        "entrypoint_mode": "explicit_entrypoint",
        "stream_llm_deltas": True,
        "allowed_tool_intent_count": 1,
        "allowed_memory_scope_count": 1,
    }

    descriptor = agent.descriptor()
    assert descriptor.name == "support_agent"
    assert descriptor.type == "general_assistant"
    assert descriptor.llm_profile == "local_reasoning"
    assert descriptor.capabilities.answer is True
    assert descriptor.capabilities.stream is True
    assert descriptor.capabilities.tool_intents is True


def test_agent_factory_requires_custom_entrypoint() -> None:
    config = FakeConfigurationView(
        {
            "agents": {
                "plugins": {
                    "custom_agent": {
                        "enabled": True,
                        "type": "custom",
                    }
                }
            }
        }
    )
    settings = get_agents_settings(config)
    factory = AgentFactory(settings=settings)

    with pytest.raises(
        ConfigurationError,
        match="Custom agent 'custom_agent' requires module and class_name",
    ):
        factory.build(settings.plugins["custom_agent"])