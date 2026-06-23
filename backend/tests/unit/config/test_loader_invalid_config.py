from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_prepared_config, load_validated_config
from app.contracts.errors import ConfigurationError

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"


def test_load_prepared_config_rejects_missing_required_env_fixture() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_prepared_config(FIXTURES_DIR / "invalid_missing_env.yaml", env={})

    message = str(exc_info.value)
    assert "REQUIRED_LLM_BASE_URL" in message
    assert "llm.providers.local_provider.base_url" in message


def test_load_prepared_config_rejects_literal_secret_fixture() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_prepared_config(FIXTURES_DIR / "invalid_secret_literal.yaml", env={})

    message = str(exc_info.value)
    assert "llm.providers.local_provider.api_key" in message
    assert "sk-real-secret-key" not in message


def test_load_validated_config_rejects_unknown_yaml_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "unknown-keys.yaml"
    config_path.write_text(
        (FIXTURES_DIR / "valid_minimal.yaml").read_text(encoding="utf-8")
        + "\nunknown_section:\n  enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(config_path, env={})

    assert "unknown_section" in str(exc_info.value)


def test_load_yaml_mapping_requires_root_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "not-a-mapping.yaml"
    config_path.write_text("- item\n- item2\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_prepared_config(config_path, env={})

    assert "YAML mapping" in str(exc_info.value)