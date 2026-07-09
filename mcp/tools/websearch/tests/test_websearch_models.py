from __future__ import annotations

import pytest

from tools.websearch.models import (
    WebSearchProviderError,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
    WebSearchToolConfig,
)


def test_websearch_request_normalizes_and_bounds_query() -> None:
    request = WebSearchRequest(query="  open   source   mcp  ")

    assert request.query == "open source mcp"
    assert request.max_results == 5


def test_websearch_request_rejects_blank_query() -> None:
    with pytest.raises(ValueError, match="query"):
        WebSearchRequest(query="   ")


def test_websearch_tool_config_requires_title_and_url_fields() -> None:
    with pytest.raises(ValueError, match="title"):
        WebSearchToolConfig(allowed_result_fields=["href", "body"])

    with pytest.raises(ValueError, match="href or url"):
        WebSearchToolConfig(allowed_result_fields=["title", "body"])


def test_websearch_result_rejects_oversized_fields() -> None:
    with pytest.raises(ValueError, match="at most 200"):
        WebSearchResult(
            rank=1,
            title="x" * 201,
            url="https://example.com",
            snippet="snippet",
            source="duckduckgo",
        )


def test_websearch_response_requires_matching_counts_and_error_shape() -> None:
    result = WebSearchResult(
        rank=1,
        title="Example",
        url="https://example.com",
        snippet="A result.",
        source="duckduckgo",
    )

    with pytest.raises(ValueError, match="result_count"):
        WebSearchResponse(
            query="example",
            provider="ddgs",
            backend="duckduckgo",
            region="us-en",
            safesearch="moderate",
            max_results=5,
            result_count=0,
            results=[result],
        )

    with pytest.raises(ValueError, match="must include an error"):
        WebSearchResponse(
            ok=False,
            query="example",
            provider="ddgs",
            backend="duckduckgo",
            region="us-en",
            safesearch="moderate",
            max_results=5,
            result_count=0,
            results=[],
        )


def test_websearch_response_from_error_is_safe_and_empty() -> None:
    response = WebSearchResponse.from_error(
        query="example",
        provider="ddgs",
        backend="duckduckgo",
        region="us-en",
        safesearch="moderate",
        time_limit=None,
        max_results=5,
        error=WebSearchProviderError(
            code="provider_unavailable",
            message="Web search provider is unavailable.",
            retryable=True,
        ),
    )

    assert response.ok is False
    assert response.result_count == 0
    assert response.results == []
    assert response.error is not None
    assert response.error.retryable is True