"""Process entry point for the standalone MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from fastmcp import FastMCP

from app.bootstrap import bootstrap
from app.errors import MCPConfigurationError


TransportName = Literal["stdio", "http", "sse", "streamable-http"]


def _resolve_transport(transport: object) -> TransportName:
    if transport in {"stdio", "http", "sse", "streamable-http"}:
        return cast(TransportName, transport)

    raise MCPConfigurationError(f"Unsupported MCP transport: {transport!r}")


def create_server(config_path: str | Path | None = None) -> FastMCP:
    runtime = bootstrap(config_path)
    return runtime.server


def main(config_path: str | Path | None = None) -> None:
    runtime = bootstrap(config_path)
    server_config = runtime.settings.server
    transport = _resolve_transport(server_config.transport)

    runtime.server.run(
        transport=transport,
        host=server_config.host,
        port=server_config.port,
        path=server_config.path,
    )


if __name__ == "__main__":
    main()
