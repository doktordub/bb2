from pathlib import Path

from app.bootstrap import bootstrap
from app.tools_base.manifest import ToolManifest
from app.tools_base.plugin import ToolPlugin
from app.tools_base.validation import load_manifest, load_tool_config, validate_plugin_instance
from tools.example_tool.plugin import create_plugin


EXAMPLE_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "tools" / "example_tool" / "manifest.yaml"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tools" / "example_tool" / "config.yaml"


def test_create_plugin_matches_contract() -> None:
    runtime = bootstrap()
    manifest = load_manifest(EXAMPLE_MANIFEST_PATH)
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=load_tool_config(EXAMPLE_CONFIG_PATH),
    )

    plugin = create_plugin(context)
    validate_plugin_instance(plugin, manifest)

    assert isinstance(plugin, ToolPlugin)
    assert plugin.name == "example_tool"
    assert plugin.version == "1.0.0"
    assert plugin.capabilities == manifest.capability_descriptors()


def test_manifest_descriptor_conversion_is_stable() -> None:
    manifest = ToolManifest.model_validate(load_manifest(EXAMPLE_MANIFEST_PATH).model_dump())

    descriptors = manifest.tool_descriptors()

    assert len(descriptors) == 1
    assert descriptors[0].name == "example.echo"
    assert descriptors[0].risk_level == "read_only"