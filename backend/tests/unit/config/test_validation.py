from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.contracts.errors import ConfigurationError

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"
BASE_FIXTURE_PATH = FIXTURES_DIR / "valid_minimal.yaml"


@pytest.mark.parametrize(
    ("override_name", "expected_message"),
    [
        ("api_invalid_cors_origin.yaml", "api.cors.allow_origins"),
        ("api_invalid_request_limit.yaml", "api.request_limits.max_body_bytes"),
        ("api_invalid_timeout.yaml", "api.request_limits.request_timeout_seconds"),
        ("api_invalid_header_name.yaml", "api.sessions.session_id_header"),
    ],
)
def test_load_validated_config_rejects_invalid_api_configuration(
    override_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_validated_config(
            BASE_FIXTURE_PATH,
            override_path=FIXTURES_DIR / override_name,
            env={},
        )

    assert expected_message in str(exc_info.value)