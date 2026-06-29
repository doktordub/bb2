from __future__ import annotations

from pathlib import Path

from app.config.loader import load_validated_config
from app.config.view import ValidatedConfigurationView


FIXTURES_DIR = Path("tests/fixtures/config")


def test_policy_denied_fixture_is_valid_runtime_example() -> None:
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / "orchestration_policy_denied.yaml",
        env={},
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    assert config.require("llm.defaults.profile") == "policy_denied_profile"
    assert config.require("orchestration.strategies.direct_agent.llm_profile") == "policy_denied_profile"
    assert config.require("orchestration.usecases.default_chat.llm_profile") == "policy_denied_profile"
    assert tuple(config.require("llm.profiles.policy_denied_profile.allowed_for.agents")) == ("other_agent",)


def test_fallback_answer_fixture_is_valid_runtime_example() -> None:
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / "orchestration_fallback_answer.yaml",
        env={},
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    assert config.require("orchestration.defaults.strategy") == "fallback_answer"
    assert config.require("orchestration.defaults.fallback_strategy") == "fallback_answer"
    assert config.require("orchestration.strategies.fallback_answer.type") == "fallback_answer"
    assert config.require("orchestration.strategies.fallback_answer.message")
    assert tuple(config.require("orchestration.usecases.fallback_chat.allowed_strategies")) == (
        "fallback_answer",
    )


def test_memory_update_fixture_is_valid_runtime_example() -> None:
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / "orchestration_memory_update.yaml",
        env={},
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    assert config.require("memory.enabled") is True
    assert config.require("memory.lifecycle.allow_writes") is True
    assert config.require("policy.profiles.default.allow_memory_writes") is True
    assert config.require("orchestration.strategies.memory_update.type") == "memory_update"
    assert config.require("orchestration.strategies.memory_update.memory_write_enabled") is True
    assert config.require("orchestration.strategies.memory_update.max_memory_writes") == 1


def test_disabled_bounded_planner_fixture_is_valid_runtime_example() -> None:
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / "orchestration_bounded_planner_disabled.yaml",
        env={},
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    assert config.require("orchestration.strategies.bounded_planner.enabled") is False
    assert config.require("orchestration.strategies.bounded_planner.type") == "bounded_planner"
    assert config.require("orchestration.strategies.bounded_planner.max_plan_steps") == 4
    assert config.require("orchestration.strategies.bounded_planner.max_execute_steps") == 4
