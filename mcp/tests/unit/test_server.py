from fastmcp import FastMCP

from app.bootstrap import bootstrap
from app.main import create_server
from app.server import build_server


def test_build_server_returns_fastmcp_instance() -> None:
    runtime = bootstrap()
    server = build_server(runtime.services)

    assert isinstance(server, FastMCP)


def test_create_server_uses_default_bootstrap_config() -> None:
    server = create_server()
    runtime = bootstrap()

    assert isinstance(server, FastMCP)
    assert runtime.settings.server.name == "main_mcp"


async def test_create_server_registers_health_tool_by_default() -> None:
    server = create_server()
    tools = await server.list_tools()

    assert any(tool.name == "mcp.health" for tool in tools)
