from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.view import ValidatedConfigurationView, get_agents_settings


FIXTURES_DIR = Path("tests/fixtures/config")


def _load_agent_settings(override_name: str):
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / override_name,
        env={},
    )
    return get_agents_settings(ValidatedConfigurationView(parsed.model_dump(mode="python")))


@pytest.mark.parametrize(
    (
        "override_name",
        "expected_type",
        "expected_prompt_profile",
        "answer_enabled",
        "review_enabled",
        "memory_read_enabled",
        "tool_intents_enabled",
        "expected_module",
        "expected_class_name",
    ),
    [
        (
            "agents_general_assistant.yaml",
            "general_assistant",
            "general_assistant_v1",
            True,
            False,
            False,
            False,
            None,
            None,
        ),
        (
            "agents_document_qa.yaml",
            "document_qa",
            "document_qa_v1",
            True,
            False,
            True,
            False,
            "app.testing.fakes.fake_agent",
            "FakeAgent",
        ),
        (
            "agents_tool_using.yaml",
            "tool_using",
            "tool_using_v1",
            True,
            False,
            False,
            True,
            "app.testing.fakes.fake_agent",
            "FakeAgent",
        ),
        (
            "agents_project.yaml",
            "project_agent",
            "project_agent_v1",
            True,
            False,
            True,
            True,
            "app.testing.fakes.fake_agent",
            "FakeAgent",
        ),
        (
            "agents_memory_curator.yaml",
            "memory_curator",
            "memory_curator_v1",
            False,
            False,
            False,
            False,
            "app.testing.fakes.fake_agent",
            "FakeAgent",
        ),
        (
            "agents_reviewer.yaml",
            "reviewer",
            "reviewer_v1",
            False,
            True,
            False,
            False,
            "app.testing.fakes.fake_agent",
            "FakeAgent",
        ),
        (
            "agents_custom_legacy.yaml",
            "custom",
            None,
            True,
            False,
            False,
            False,
            "app.testing.fakes.fake_agent",
            "FakeAgent",
        ),
    ],
)
def test_agent_fixture_examples_are_valid_runtime_examples(
    override_name: str,
    expected_type: str,
    expected_prompt_profile: str | None,
    answer_enabled: bool,
    review_enabled: bool,
    memory_read_enabled: bool,
    tool_intents_enabled: bool,
    expected_module: str | None,
    expected_class_name: str | None,
) -> None:
    settings = _load_agent_settings(override_name)

    plugin = settings.plugins["support_agent"]

    assert plugin.enabled is True
    assert plugin.type == expected_type
    assert plugin.prompt_profile == expected_prompt_profile
    assert plugin.capabilities.answer is answer_enabled
    assert plugin.capabilities.review is review_enabled
    assert plugin.capabilities.memory_read is memory_read_enabled
    assert plugin.capabilities.tool_intents is tool_intents_enabled
    assert plugin.module == expected_module
    assert plugin.class_name == expected_class_name

    if expected_prompt_profile is not None:
        assert settings.strict_prompt_profile_validation is True
        assert expected_prompt_profile in settings.known_prompt_profiles