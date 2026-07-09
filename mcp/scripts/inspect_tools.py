"""Inspect safe MCP tool metadata from a running local MCP server."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


DEFAULT_ENDPOINT = "http://127.0.0.1:9001/mcp"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"MCP endpoint to inspect. Defaults to {DEFAULT_ENDPOINT}.",
    )
    parser.add_argument(
        "--bearer-token",
        default=None,
        help="Optional bearer token used for MCP transport authentication.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15,
        help="Timeout applied to internal MCP inspection tool calls.",
    )
    return parser


async def _inspect_tools(
    *,
    endpoint: str,
    bearer_token: str | None,
    timeout_seconds: int,
) -> None:
    transport = StreamableHttpTransport(
        endpoint,
        auth=bearer_token,
        headers={"x-trace-id": "trace-mcp-inspect-0001"},
    )

    async with Client(transport) as client:
        raw_tools = await client.list_tools()
        capability_result = await client.call_tool(
            "mcp.capabilities",
            {},
            timeout=timeout_seconds,
        )

    capabilities = _capabilities_payload(capability_result.structured_content)
    schema_presence = {
        tool.name: bool(getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None))
        for tool in raw_tools
    }

    rows = []
    for capability in capabilities:
        tool_name = _read_str(capability.get("tool_name")) or "<unknown>"
        rows.append(
            {
                "tool_name": tool_name,
                "capability": _read_str(capability.get("capability_name")) or "<unknown>",
                "risk_level": _read_str(capability.get("risk_level")) or "unknown",
                "enabled": bool(capability.get("enabled", False)),
                "status": _read_str(capability.get("status")) or "unknown",
                "schema_present": schema_presence.get(tool_name, False),
            }
        )

    if not rows:
        print("No plugin capabilities were returned by mcp.capabilities.")
        return

    _print_rows(rows)


def _capabilities_payload(structured_content: Any) -> list[dict[str, Any]]:
    if not isinstance(structured_content, dict):
        return []
    capabilities = structured_content.get("capabilities")
    if not isinstance(capabilities, list):
        return []
    return [item for item in capabilities if isinstance(item, dict)]


def _read_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _print_rows(rows: Iterable[dict[str, Any]]) -> None:
    ordered_rows = list(rows)
    headers = [
        ("tool_name", "tool name"),
        ("capability", "capability"),
        ("risk_level", "risk level"),
        ("enabled", "enabled"),
        ("status", "status"),
        ("schema_present", "schema"),
    ]
    widths = {
        key: max(len(label), *(len(str(row[key])) for row in ordered_rows))
        for key, label in headers
    }

    header_line = "  ".join(label.ljust(widths[key]) for key, label in headers)
    separator_line = "  ".join("-" * widths[key] for key, _label in headers)
    print(header_line)
    print(separator_line)

    for row in ordered_rows:
        print(
            "  ".join(
                str(row[key]).ljust(widths[key])
                for key, _label in headers
            )
        )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(
        _inspect_tools(
            endpoint=args.endpoint,
            bearer_token=args.bearer_token,
            timeout_seconds=max(1, args.timeout_seconds),
        )
    )


if __name__ == "__main__":
    main()