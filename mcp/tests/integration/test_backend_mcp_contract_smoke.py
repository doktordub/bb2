from __future__ import annotations

import os

import httpx
import pytest


BACKEND_BASE_URL = os.getenv("BB2_BACKEND_BASE_URL", "http://127.0.0.1:8000")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("BB2_RUN_LIVE_BACKEND_MCP_TESTS") != "1",
    reason="Live backend-to-MCP contract smoke tests are opt-in.",
)
async def test_live_backend_reports_mcp_ready_and_tooling_enabled() -> None:
    async with httpx.AsyncClient(base_url=BACKEND_BASE_URL, timeout=20.0) as client:
        health_response = await client.get(
            "/health",
            headers={"x-trace-id": "trace-backend-mcp-health-0001"},
        )
        capabilities_response = await client.get(
            "/capabilities",
            headers={"x-trace-id": "trace-backend-mcp-capabilities-0001"},
        )

    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["trace_id"] == "trace-backend-mcp-health-0001"
    assert health_payload["mcp"]["configured"] is True
    assert health_payload["mcp"]["tooling_enabled"] is True
    assert health_payload["mcp"]["adapter_reachable"] is True, (
        "The running backend has not refreshed its MCP connection state. "
        "Start the MCP server first, then restart the backend so startup discovery runs "
        "against the live endpoint."
    )
    assert health_payload["mcp"]["mcp_status"] == "ok"
    assert health_payload["mcp"]["discovery_enabled"] is True
    assert health_payload["mcp"]["tools_discovered"] >= 1

    assert capabilities_response.status_code == 200
    capabilities_payload = capabilities_response.json()
    assert capabilities_payload["trace_id"] == "trace-backend-mcp-capabilities-0001"
    assert capabilities_payload["data"]["tools"]["enabled"] is True
    assert capabilities_payload["data"]["tools"]["configured"] is True
    assert capabilities_payload["data"]["tools"]["discovery_enabled"] is True
    assert capabilities_payload["data"]["tools"]["total_tools"] >= 1