from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.view import ValidatedConfigurationView
from app.tools.errors import ToolArgumentValidationError
from app.tools.factory import build_tooling_runtime


def _build_runtime(override_name: str):
    parsed = load_validated_config(
        Path("tests/fixtures/config/valid_minimal.yaml"),
        override_path=Path("tests/fixtures/config") / override_name,
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    return build_tooling_runtime(config)


def test_secret_like_argument_fixture_is_valid_runtime_example() -> None:
    runtime = _build_runtime("tooling_invalid_secret_like_arguments.yaml")

    definition = runtime.registry.resolve("project.inspect")

    assert runtime.settings.enabled is True
    assert runtime.settings.mcp_server.endpoint == "http://tooling.invalid/mcp"
    assert definition.approval_required is False

    with pytest.raises(ToolArgumentValidationError, match="secret-like fields"):
        runtime.argument_validator.validate(
            definition,
            {"query": "phase 9", "api_token": "secret"},
        )


def test_approval_required_fixture_is_valid_runtime_example() -> None:
    runtime = _build_runtime("tooling_approval_required.yaml")

    definition = runtime.registry.resolve("billing.charge")

    assert runtime.settings.enabled is True
    assert definition.approval_required is True
    assert definition.safety_level == "write"
    assert definition.mcp_tool_name == "billing.charge"