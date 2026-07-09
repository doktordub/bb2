from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.bootstrap import bootstrap
from app.context import ToolRuntimeContext
from tools.websearch.models import WebSearchRequest
from tools.websearch.service import WebSearchService


WEBSEARCH_TOOL_DIR = Path(__file__).resolve().parents[1]


class RecordingRateLimiter:
    mode_name = "recording"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def check(self, key: str) -> None:
        self.calls.append(key)


class StubDDGSClient:
    def __init__(self, results: list[dict[str, Any]] | Exception) -> None:
        self.results = results
        self.closed = False
        self.calls: list[dict[str, Any]] = []

    def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"query": query, **kwargs})
        if isinstance(self.results, Exception):
            raise self.results
        return list(self.results)

    def close(self) -> None:
        self.closed = True


def build_context(tool_config: dict[str, Any], rate_limiter: RecordingRateLimiter) -> ToolRuntimeContext:
    runtime = bootstrap()
    return ToolRuntimeContext(
        server_name=runtime.settings.server.name,
        environment=runtime.settings.server.environment,
        tool_name="websearch",
        tool_config=tool_config,
        app_config=runtime.settings,
        logger=runtime.services.logger,
        redactor=runtime.services.redactor,
        secrets=runtime.services.secret_resolver,
        http_client_factory=runtime.services.http_client_factory,
        auth=None,
        outbound_auth=None,
        rate_limiter=rate_limiter,
        metrics=None,
        tracer=None,
        clock=runtime.services.clock,
    )


def build_tool_config() -> dict[str, Any]:
    return {
        "provider": "ddgs",
        "backend": "duckduckgo",
        "region": "us-en",
        "safesearch": "moderate",
        "time_limit": None,
        "max_results": 10,
        "max_query_chars": 500,
        "timeout_seconds": 15,
        "cache_seconds": 300,
        "allowed_result_fields": ["title", "href", "body"],
        "result_limits": {
            "max_title_chars": 200,
            "max_url_chars": 1000,
            "max_snippet_chars": 500,
            "max_results": 10,
        },
    }


async def test_websearch_service_normalizes_results_and_uses_rate_limit_and_cache() -> None:
    rate_limiter = RecordingRateLimiter()
    stub_client = StubDDGSClient(
        [
            {
                "title": "  Example    Result  " + ("x" * 250),
                "href": "https://example.com/" + ("a" * 1200),
                "body": "  Snippet   text  " + ("y" * 650),
            },
            {"href": "https://missing-title.example.com", "body": "Missing title."},
            {
                "title": "Second result",
                "href": "https://example.org",
                "body": "Another result.",
                "source": "DuckDuckGo",
            },
        ]
    )

    def ddgs_factory(timeout_seconds: int, verify: bool | str) -> StubDDGSClient:
        assert timeout_seconds == 15
        assert verify is True
        return stub_client

    service = WebSearchService(
        build_context(build_tool_config(), rate_limiter),
        ddgs_factory=ddgs_factory,
    )

    first_response = await service.search(WebSearchRequest(query="  example query  ", max_results=3))
    second_response = await service.search(WebSearchRequest(query="example query", max_results=3))

    assert rate_limiter.calls == ["websearch.search", "websearch.search"]
    assert len(stub_client.calls) == 1
    assert stub_client.closed is True
    assert first_response.ok is True
    assert first_response.cached is False
    assert first_response.result_count == 2
    assert first_response.results[0].rank == 1
    assert len(first_response.results[0].title) == 200
    assert len(first_response.results[0].url) == 1000
    assert len(first_response.results[0].snippet) == 500
    assert first_response.results[1].source == "DuckDuckGo"
    assert second_response.cached is True
    assert second_response.results == first_response.results


async def test_websearch_service_maps_strict_safesearch_and_limits_requested_results() -> None:
    rate_limiter = RecordingRateLimiter()
    stub_client = StubDDGSClient(
        [
            {
                "title": "One",
                "href": "https://example.com/1",
                "body": "First",
            }
        ]
    )

    service = WebSearchService(
        build_context(build_tool_config(), rate_limiter),
        ddgs_factory=lambda timeout_seconds, verify: stub_client,
    )

    response = await service.search(
        WebSearchRequest(
            query="strict",
            max_results=25,
            safesearch="strict",
            time_limit="m",
        )
    )

    assert response.ok is True
    assert stub_client.calls[0]["max_results"] == 10
    assert stub_client.calls[0]["safesearch"] == "on"
    assert stub_client.calls[0]["timelimit"] == "m"


async def test_websearch_service_returns_safe_provider_errors() -> None:
    rate_limiter = RecordingRateLimiter()
    service = WebSearchService(
        build_context(build_tool_config(), rate_limiter),
        ddgs_factory=lambda timeout_seconds, verify: StubDDGSClient(
            httpx.ReadTimeout("timed out")
        ),
    )

    response = await service.search(WebSearchRequest(query="timeout"))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "provider_timeout"
    assert response.error.retryable is True
    assert response.results == []


async def test_websearch_service_retries_transient_provider_errors() -> None:
    rate_limiter = RecordingRateLimiter()
    attempt_count = 0

    class FlakyDDGSClient:
        def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
            del query, kwargs
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                raise OSError("temporary failure")
            return [{"title": "Recovered", "href": "https://example.com", "body": "Retry ok."}]

        def close(self) -> None:
            return None

    service = WebSearchService(
        build_context(build_tool_config(), rate_limiter),
        ddgs_factory=lambda timeout_seconds, verify: FlakyDDGSClient(),
    )

    response = await service.search(WebSearchRequest(query="retry"))

    assert attempt_count == 2
    assert response.ok is True
    assert response.result_count == 1


async def test_websearch_service_rejects_queries_above_configured_max_query_chars() -> None:
    rate_limiter = RecordingRateLimiter()
    tool_config = build_tool_config()
    tool_config["max_query_chars"] = 10

    service = WebSearchService(
        build_context(tool_config, rate_limiter),
        ddgs_factory=lambda timeout_seconds, verify: StubDDGSClient([]),
    )

    response = await service.search(WebSearchRequest(query="x" * 11))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "invalid_request"