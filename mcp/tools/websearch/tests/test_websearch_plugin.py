from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from app.bootstrap import bootstrap
from app.tools_base.validation import load_manifest, load_tool_config, validate_plugin_instance
from tools.websearch.models import WebSearchRequest, WebSearchResponse, WebSearchResult
from tools.websearch.plugin import WebSearchPlugin, create_plugin


WEBSEARCH_TOOL_DIR = Path(__file__).resolve().parents[1]


class StubWebSearchService:
    def __init__(self) -> None:
        self.requests: list[WebSearchRequest] = []

    async def search(self, request: WebSearchRequest) -> WebSearchResponse:
        self.requests.append(request)
        return WebSearchResponse(
            query=request.query,
            provider="ddgs",
            backend="duckduckgo",
            region=request.region or "us-en",
            safesearch=request.safesearch or "moderate",
            time_limit=request.time_limit,
            max_results=request.max_results,
            result_count=1,
            results=[
                WebSearchResult(
                    rank=1,
                    title="Example",
                    url="https://example.com",
                    snippet="Example result.",
                    source="duckduckgo",
                )
            ],
        )

    def health_payload(self) -> dict[str, str]:
        return {
            "status": "ok",
            "provider": "ddgs",
            "network_check": "skipped",
        }


async def test_websearch_plugin_registers_and_executes() -> None:
    runtime = bootstrap()
    manifest = load_manifest(WEBSEARCH_TOOL_DIR / "manifest.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=load_tool_config(WEBSEARCH_TOOL_DIR / "config.yaml"),
    )

    plugin = WebSearchPlugin(context, service=StubWebSearchService())
    validate_plugin_instance(plugin, manifest)

    server = FastMCP("websearch-contract-test")
    plugin.register(server)
    tools = await server.list_tools()
    result = await server.call_tool(
        "websearch.search",
        {
            "query": "mcp search",
            "max_results": 3,
            "safesearch": "strict",
        },
    )

    assert any(tool.name == "websearch.search" for tool in tools)
    assert result.structured_content == {
        "ok": True,
        "query": "mcp search",
        "provider": "ddgs",
        "backend": "duckduckgo",
        "region": "us-en",
        "safesearch": "strict",
        "time_limit": None,
        "max_results": 3,
        "result_count": 1,
        "results": [
            {
                "rank": 1,
                "title": "Example",
                "url": "https://example.com",
                "snippet": "Example result.",
                "source": "duckduckgo",
            }
        ],
        "cached": False,
        "error": None,
    }


async def test_websearch_plugin_health_is_safe_and_bounded() -> None:
    runtime = bootstrap()
    manifest = load_manifest(WEBSEARCH_TOOL_DIR / "manifest.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=load_tool_config(WEBSEARCH_TOOL_DIR / "config.yaml"),
    )

    plugin = create_plugin(context)
    health = await plugin.health()

    assert health.state == "ok"
    assert health.details == {
        "status": "ok",
        "provider": "ddgs",
        "network_check": "skipped",
    }