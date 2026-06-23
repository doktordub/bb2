from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import YamlConfigurationLoader, load_prepared_config, load_validated_config

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
    assert config.llm.default_profile == "local_reasoning"
    assert config.persistence.memory.provider == "memory_store"
    assert config.observability.trace_enabled is True
    assert config.observability.trace_store_required is True
    assert config.observability.max_trace_payload_chars == 4000
    assert config.observability.slow_tool_call_ms == 5000
    assert config.health.include_component_details is True


def test_load_validated_config_parses_valid_full_fixture() -> None:
    config = load_validated_config(FIXTURES_DIR / "valid_full.yaml", env={})

    assert config.app.active_usecase == "support_chat"
    assert set(config.usecases) == {"support_chat", "routing_chat"}
    assert config.strategies["router"].llm_profile == "cloud_fast"
    assert config.llm.profiles["cloud_fast"].fallback_profiles == ["local_reasoning"]
    assert config.observability.trace_enabled is True
    assert config.observability.trace_payloads_enabled is True
    assert config.observability.max_trace_payload_chars == 12000
    assert config.observability.metrics_enabled is True
    assert config.health.include_component_details is True


async def test_yaml_configuration_loader_returns_validated_view() -> None:
    loader = YamlConfigurationLoader(FIXTURES_DIR / "valid_minimal.yaml", env={})

    view = await loader.load()

    assert view.require("app.active_usecase") == "default_chat"
    assert view.section("llm")["default_profile"] == "local_reasoning"


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