from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.contracts.errors import ConfigurationError

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"


@pytest.mark.parametrize(
    ("fixture_name", "expected_message"),
    [
        ("invalid_missing_active_usecase.yaml", "Active use case 'missing_chat'"),
        ("invalid_unknown_strategy.yaml", "unknown strategy 'missing_strategy'"),
        ("invalid_unknown_agent.yaml", "unknown default agent 'missing_agent'"),
        ("invalid_unknown_llm_provider.yaml", "unknown provider 'missing_provider'"),
        ("invalid_unknown_llm_profile.yaml", "unknown LLM profile 'missing_profile'"),
        ("invalid_fallback_cycle.yaml", "LLM fallback cycle detected"),
    ],
)
def test_load_validated_config_rejects_invalid_cross_references(
    fixture_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(FIXTURES_DIR / fixture_name, env={})

    assert expected_message in str(exc_info.value)