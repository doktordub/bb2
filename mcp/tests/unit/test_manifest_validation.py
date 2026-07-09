from pathlib import Path

import pytest

from app.errors import MCPToolManifestError
from app.tools_base.validation import load_manifest


EXAMPLE_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "tools" / "example_tool" / "manifest.yaml"


def test_load_manifest_accepts_valid_example_manifest() -> None:
    manifest = load_manifest(EXAMPLE_MANIFEST_PATH)

    assert manifest.name == "example_tool"
    assert manifest.package == "mcp.tools.example_tool"
    assert manifest.status == "experimental"


def test_load_manifest_rejects_duplicate_tool_names(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "example_tool"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "manifest.yaml"
    manifest_path.write_text(
        """
name: example_tool
package: mcp.tools.example_tool
version: 1.0.0
status: experimental
owner: platform
required: false
description: Invalid manifest.
capabilities:
  - name: example.echo
    type: tool
    risk_level: read_only
    description: Echo capability.
tools:
  - name: example.echo
    function: echo
    capability: example.echo
    description: First tool.
    risk_level: read_only
    input_schema: auto
  - name: example.echo
    function: echo_again
    capability: example.echo
    description: Duplicate tool.
    risk_level: read_only
    input_schema: auto
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(MCPToolManifestError, match="tool names must be unique"):
        load_manifest(manifest_path)


def test_load_manifest_requires_explicit_risk_levels(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "example_tool"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "manifest.yaml"
    manifest_path.write_text(
        """
name: example_tool
package: mcp.tools.example_tool
version: 1.0.0
status: experimental
owner: platform
required: false
description: Invalid manifest.
capabilities:
  - name: example.echo
    type: tool
    description: Missing risk level.
tools: []
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(MCPToolManifestError, match="risk_level"):
        load_manifest(manifest_path)