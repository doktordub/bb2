from pathlib import Path

from fastmcp import FastMCP

from app.bootstrap import bootstrap
from app.tools_base.validation import load_manifest, load_tool_config, validate_plugin_instance
from tools.example_tool.plugin import create_plugin


EXAMPLE_TOOL_DIR = Path(__file__).resolve().parents[2] / "tools" / "example_tool"


async def test_example_plugin_registers_and_executes() -> None:
    runtime = bootstrap()
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")
    config = load_tool_config(EXAMPLE_TOOL_DIR / "config.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=config,
    )

    plugin = create_plugin(context)
    validate_plugin_instance(plugin, manifest)

    server = FastMCP("contract-test")
    plugin.register(server)
    tools = await server.list_tools()
    result = await server.call_tool(
        "example.echo",
        {
            "message": "hello",
            "uppercase": True,
        },
    )

    assert any(tool.name == "example.echo" for tool in tools)
    assert result.structured_content is not None
    assert result.structured_content["ok"] is True
    assert result.structured_content["data"]["message"] == "example: HELLO"
    assert result.structured_content["data"]["uppercase_applied"] is True


async def test_example_plugin_health_is_safe_and_bounded() -> None:
    runtime = bootstrap()
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=load_tool_config(EXAMPLE_TOOL_DIR / "config.yaml"),
    )

    plugin = create_plugin(context)
    health = await plugin.health()

    assert health.state == "ok"
    assert health.details == {
        "tool_name": "example_tool",
        "configured_prefix": "example",
    }