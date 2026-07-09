from __future__ import annotations

import os

import pytest

from app.bootstrap import bootstrap
RUN_EXTERNAL_TESTS = os.getenv("RUN_EXTERNAL_NETWORK_TESTS") == "1"

pytestmark = [pytest.mark.integration, pytest.mark.external_network]


@pytest.mark.skipif(
    not RUN_EXTERNAL_TESTS,
    reason="Set RUN_EXTERNAL_NETWORK_TESTS=1 to run live DDGS smoke tests.",
)
@pytest.mark.asyncio
async def test_websearch_external_ddgs_smoke() -> None:
    pytest.importorskip("ddgs")
    runtime = bootstrap()
    response = None
    for _ in range(3):
        result = await runtime.server.call_tool(
            "websearch.search",
            {"query": "python programming", "max_results": 1},
        )
        response = result.structured_content
        if response is not None and response["ok"] is True:
            break

    assert response is not None
    if response["ok"] is not True:
        error = response.get("error") or {}
        if error.get("code") in {
            "provider_unavailable",
            "provider_rate_limited",
            "provider_timeout",
        }:
            pytest.skip(f"DDGS smoke test skipped: {error.get('message', 'provider unavailable')}")

    assert response["ok"] is True, response.get("error")
    assert 0 < response["result_count"] <= 1
    assert all(result_item["title"] for result_item in response["results"])
    assert all(result_item["url"].startswith("http") for result_item in response["results"])