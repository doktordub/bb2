from __future__ import annotations

from pathlib import Path
import os

import pytest

from app.agents.builtin_catalog import clear_builtin_agent_catalog_cache, load_builtin_agent_catalog
from app.config.loader import YamlConfigurationLoader, load_prepared_config, load_validated_config
from app.orchestration.message_catalog import clear_message_catalog_cache, load_message_catalog

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"


def test_load_prepared_config_merges_override_and_resolves_env_values(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    override_path = tmp_path / "override.yaml"
    base_path.write_text(
        "service:\n"
        "  nested:\n"
        "    enabled: true\n"
        "    tags:\n"
        "      - base\n"
        "  scalar: base\n"
        "  path: ${env:APP_DATA_DIR:./data}/workflow_state.db\n",
        encoding="utf-8",
    )
    override_path.write_text(
        "service:\n"
        "  nested:\n"
        "    retries: 3\n"
        "    tags:\n"
        "      - override\n"
        "  scalar: override\n",
        encoding="utf-8",
    )

    prepared = load_prepared_config(
        base_path,
        override_path=override_path,
        env={"APP_DATA_DIR": "var/data"},
    )

    assert prepared == {
        "service": {
            "nested": {
                "enabled": True,
                "retries": 3,
                "tags": ["override"],
            },
            "scalar": "override",
            "path": "var/data/workflow_state.db",
        }
    }


def test_load_validated_config_parses_valid_minimal_fixture() -> None:
    config = load_validated_config(FIXTURES_DIR / "valid_minimal.yaml", env={})

    assert config.app.active_usecase == "default_chat"
    assert config.orchestration.defaults.strategy == "direct_agent"
    assert config.orchestration.strategies["direct_agent"].type == "direct_agent"
    assert config.usecases["default_chat"].default_agent == "support_agent"
    assert config.llm.defaults.profile == "local_reasoning"
    assert config.memory.enabled is False
    assert config.memory.provider == "memory_store"
    assert config.memory.required is False
    assert config.persistence.memory.provider == "memory_store"
    assert config.observability.trace_enabled is True
    assert config.observability.trace_store_required is True
    assert config.observability.max_trace_payload_chars == 4000
    assert config.observability.slow_tool_call_ms == 5000
    assert config.health.include_component_details is True


def test_load_validated_config_parses_valid_full_fixture() -> None:
    config = load_validated_config(FIXTURES_DIR / "valid_full.yaml", env={})

    assert config.app.active_usecase == "support_chat"
    assert config.orchestration.defaults.strategy == "direct_agent"
    assert config.orchestration.defaults.fallback_strategy == "direct_agent"
    assert set(config.usecases) == {"support_chat", "routing_chat"}
    assert config.orchestration.usecases["routing_chat"].strategy == "router"
    assert config.strategies["router"].llm_profile == "cloud_fast"
    assert config.llm.profiles["cloud_fast"].fallback_profiles == ["local_reasoning"]
    assert config.memory.provider == "memory_store"
    assert config.observability.trace_enabled is True
    assert config.observability.trace_payloads_enabled is True
    assert config.observability.max_trace_payload_chars == 12000
    assert config.observability.metrics_enabled is True
    assert config.health.include_component_details is True


def test_shipped_app_config_allows_local_reasoning_for_fallback_answer() -> None:
    config = load_validated_config("config/app.yaml", env={})

    assert "fallback_answer" in config.llm.profiles["local_reasoning"].allowed_for.strategies
    assert config.policy.visualization is not None
    assert "deterministic_synthesis" in config.policy.visualization.allowed_data_sources


def test_default_external_catalogs_exist_and_parse() -> None:
    clear_builtin_agent_catalog_cache()
    clear_message_catalog_cache()

    builtin_catalog = load_builtin_agent_catalog(validate_entrypoints=True)
    message_catalog = load_message_catalog()

    assert builtin_catalog.get("general_assistant") is not None
    assert message_catalog.get_text("fallback_answer", "default_message").startswith(
        "I could not complete"
    )


async def test_yaml_configuration_loader_returns_validated_view() -> None:
    loader = YamlConfigurationLoader(FIXTURES_DIR / "valid_minimal.yaml", env={})

    view = await loader.load()

    assert view.require("app.active_usecase") == "default_chat"
    assert view.require("llm.defaults.profile") == "local_reasoning"


def test_load_prepared_config_uses_backend_env_file_values_by_default(tmp_path: Path) -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else None
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "service:\n"
        "  base_url: ${env:LOCAL_LLM_BASE_URL:http://localhost:8081/v1}\n"
        "  log_level: ${env:APP_LOG_LEVEL:INFO}\n",
        encoding="utf-8",
    )

    os.environ.pop("LOCAL_LLM_BASE_URL", None)
    os.environ.pop("APP_LOG_LEVEL", None)
    env_path.write_text(
        "LOCAL_LLM_BASE_URL=http://env-file.example/v1\n"
        "APP_LOG_LEVEL=WARNING\n",
        encoding="utf-8",
    )

    try:
        prepared = load_prepared_config(config_path)
    finally:
        if original is None:
            env_path.unlink(missing_ok=True)
        else:
            env_path.write_text(original, encoding="utf-8")

    assert prepared == {
        "service": {
            "base_url": "http://env-file.example/v1",
            "log_level": "WARNING",
        }
    }


@pytest.mark.parametrize(
    ("override_name", "expected_strategy", "expected_usecase"),
    [
        ("orchestration_basic_direct.yaml", "direct_agent", "default_chat"),
        ("orchestration_streaming_direct.yaml", "direct_agent", "default_chat"),
        ("orchestration_retrieval_augmented.yaml", "retrieval_augmented", "document_qa"),
        ("orchestration_tool_assisted.yaml", "tool_assisted", "tooling_chat"),
        ("orchestration_router.yaml", "router", "routing_chat"),
        ("orchestration_policy_denied.yaml", "direct_agent", "default_chat"),
    ],
)
def test_load_validated_config_accepts_orchestration_override_fixtures(
    override_name: str,
    expected_strategy: str,
    expected_usecase: str,
) -> None:
    config = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / override_name,
        env={},
    )

    assert config.orchestration.defaults.strategy == expected_strategy
    assert expected_usecase in config.orchestration.usecases


@pytest.mark.parametrize(
    ("override_name", "expected_enabled", "expected_active_usecase"),
    [
        ("task_execution_chat_disabled.yaml", False, "default_chat"),
        ("task_execution_chat_staged.yaml", True, "default_chat"),
        ("task_execution_chat_enabled.yaml", True, "task_execution_chat"),
    ],
)
def test_load_validated_config_accepts_task_execution_rollout_fixtures(
    override_name: str,
    expected_enabled: bool,
    expected_active_usecase: str,
) -> None:
    config = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / override_name,
        env={},
    )

    usecase = config.orchestration.usecases["task_execution_chat"]

    assert config.app.active_usecase == expected_active_usecase
    assert usecase.enabled is expected_enabled
    assert usecase.strategy == "bounded_planner"
    assert set(usecase.allowed_agents) == {"chart_agent", "support_agent", "task_execution_agent"}
    assert set(usecase.allowed_strategies) == {"bounded_planner", "fallback_answer"}
    assert usecase.metadata["routing_mode"] == "task_first"
    assert usecase.metadata["assessment_agent"] == "task_execution_agent"
    assert usecase.metadata["keep_visualization_override_disabled"] is True
    assert config.agents.plugins["task_execution_agent"].type == "task_execution"
    assert config.agents.plugins["chart_agent"].type == "chart_agent"
    assert "task_execution_chat" in config.llm.profiles["local_reasoning"].allowed_for.usecases
    assert "task_execution_agent" in config.llm.profiles["local_reasoning"].allowed_for.agents
    assert "bounded_planner" in config.llm.profiles["local_reasoning"].allowed_for.strategies


@pytest.mark.parametrize(
    ("override_name", "expectations"),
    [
        (
            "observability_enabled.yaml",
            {
                "observability.structured_logging": True,
                "observability.trace_enabled": True,
                "observability.trace_payloads_enabled": True,
                "observability.trace_store_required": True,
                "observability.metrics_enabled": True,
            },
        ),
        (
            "observability_trace_payloads_disabled.yaml",
            {
                "observability.trace_payloads_enabled": False,
            },
        ),
        (
            "observability_unstructured_logging.yaml",
            {
                "observability.structured_logging": False,
            },
        ),
        (
            "health_minimal.yaml",
            {
                "health.expose_config_summary": False,
                "health.expose_provider_names": False,
                "health.include_component_details": False,
            },
        ),
        (
            "health_detailed.yaml",
            {
                "health.expose_config_summary": True,
                "health.expose_provider_names": True,
                "health.include_component_details": True,
            },
        ),
    ],
)
def test_load_validated_config_accepts_phase7_override_fixtures(
    override_name: str,
    expectations: dict[str, bool],
) -> None:
    config = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / override_name,
        env={},
    )

    config_dict = config.model_dump(mode="python")
    for path, expected in expectations.items():
        current = config_dict
        for part in path.split("."):
            current = current[part]
        assert current is expected