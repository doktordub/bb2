from pathlib import Path

import pytest

from app.errors import MCPToolConfigurationError
from app.tools_base.validation import load_manifest, load_tool_config, validate_tool_config


EXAMPLE_TOOL_DIR = Path(__file__).resolve().parents[2] / "tools" / "example_tool"


def test_validate_tool_config_accepts_valid_example_config() -> None:
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")
    config = load_tool_config(EXAMPLE_TOOL_DIR / "config.yaml")

    validate_tool_config(manifest, config)


def test_validate_tool_config_rejects_missing_required_key() -> None:
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")

    with pytest.raises(MCPToolConfigurationError, match="missing required keys"):
        validate_tool_config(manifest, {"allow_uppercase": True})


def test_validate_tool_config_rejects_wrong_type() -> None:
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")

    with pytest.raises(MCPToolConfigurationError, match="must be a boolean"):
        validate_tool_config(
            manifest,
            {
                "default_prefix": "example",
                "allow_uppercase": "yes",
            },
        )