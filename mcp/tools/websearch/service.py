"""DDGS-backed implementation of the websearch MCP tool."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from threading import Lock
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.context import ToolRuntimeContext
from app.errors import MCPToolConfigurationError

from tools.websearch.models import (
    SafeSearchValue,
    WebSearchProviderError,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
    WebSearchToolConfig,
    bound_text,
    normalize_text,
)


RATE_LIMIT_KEY = "websearch.search"


class DDGSClient(Protocol):
    """Protocol for the subset of DDGS used by the websearch tool."""

    def text(
        self,
        query: str,
        *,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: str | None = None,
        max_results: int | None = 10,
        page: int = 1,
        backend: str = "auto",
    ) -> list[dict[str, Any]]:
        ...


DDGSFactory = Callable[[int, bool | str], DDGSClient]


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Cached websearch response with an absolute expiry timestamp."""

    expires_at: datetime
    response: WebSearchResponse


def build_ddgs_client(timeout_seconds: int, verify: bool | str) -> DDGSClient:
    """Create the synchronous DDGS client lazily so imports stay optional until use."""

    try:
        from ddgs import DDGS
    except ModuleNotFoundError as error:
        raise MCPToolConfigurationError(
            "The ddgs package is required for the websearch tool. Install mcp dependencies first."
        ) from error

    return DDGS(timeout=timeout_seconds, verify=verify)


@dataclass(slots=True)
class WebSearchService:
    """Structured DDGS-backed web text search with safe normalization and caching."""

    context: ToolRuntimeContext
    ddgs_factory: DDGSFactory = build_ddgs_client
    _config: WebSearchToolConfig = field(init=False, repr=False)
    _cache: dict[str, CacheEntry] = field(default_factory=dict, init=False, repr=False)
    _cache_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            self._config = WebSearchToolConfig.model_validate(self.context.tool_config)
        except ValidationError as error:
            raise MCPToolConfigurationError(
                f"Invalid websearch tool configuration: {error}"
            ) from error

    @property
    def config(self) -> WebSearchToolConfig:
        return self._config

    async def search(self, request: WebSearchRequest) -> WebSearchResponse:
        """Run a bounded public web search and return normalized structured results."""

        if len(request.query) > self._config.max_query_chars:
            return self._build_error_response(
                request=request,
                error=WebSearchProviderError(
                    code="invalid_request",
                    message=(
                        f"query must be at most {self._config.max_query_chars} characters long."
                    ),
                    retryable=False,
                ),
            )

        effective_request = self._resolve_request(request)
        self.context.rate_limiter.check(RATE_LIMIT_KEY)

        cache_key = self._build_cache_key(effective_request)
        cached_response = self._get_cached_response(cache_key)
        if cached_response is not None:
            self.context.logger.info(
                "mcp.tool.websearch.cache_hit",
                payload={
                    "query_length": len(effective_request.query),
                    "result_count": cached_response.result_count,
                },
            )
            return cached_response

        try:
            provider_results = await self._search_provider_with_retry(effective_request)
        except Exception as error:  # pragma: no cover - normalization exercised in tests
            normalized_error = self._normalize_provider_error(error)
            self.context.logger.warning(
                "mcp.tool.websearch.provider_error",
                payload={
                    "query_length": len(effective_request.query),
                    "requested_results": effective_request.max_results,
                    "error_type": error.__class__.__name__,
                    "retryable": normalized_error.retryable,
                },
            )
            return self._build_error_response(request=effective_request, error=normalized_error)

        normalized_results = self._normalize_results(provider_results, effective_request.max_results)
        response = WebSearchResponse(
            ok=True,
            query=effective_request.query,
            provider=self._config.provider,
            backend=self._config.backend,
            region=effective_request.region or self._config.region,
            safesearch=effective_request.safesearch or self._config.safesearch,
            time_limit=effective_request.time_limit,
            max_results=effective_request.max_results,
            result_count=len(normalized_results),
            results=normalized_results,
            cached=False,
            error=None,
        )
        self._store_cached_response(cache_key, response)
        self.context.logger.info(
            "mcp.tool.websearch.search",
            payload={
                "query_length": len(effective_request.query),
                "requested_results": effective_request.max_results,
                "returned_results": response.result_count,
            },
        )
        return response

    async def _search_provider_with_retry(
        self,
        request: WebSearchRequest,
        *,
        max_attempts: int = 2,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                return await asyncio.to_thread(self._search_provider, request)
            except Exception as error:
                last_error = error

        assert last_error is not None
        raise last_error

    def health_payload(self) -> dict[str, str]:
        """Return a safe non-network health payload for plugin health checks."""

        network_check = "enabled" if self._config.deep_healthcheck else "skipped"
        return {
            "status": "ok",
            "provider": self._config.provider,
            "network_check": network_check,
        }

    def _resolve_request(self, request: WebSearchRequest) -> WebSearchRequest:
        effective_max_results = min(
            request.max_results,
            self._config.max_results,
            self._config.result_limits.max_results,
        )
        return request.model_copy(
            update={
                "max_results": effective_max_results,
                "region": request.region or self._config.region,
                "safesearch": request.safesearch or self._config.safesearch,
                "time_limit": request.time_limit
                if request.time_limit is not None
                else self._config.time_limit,
            }
        )

    def _build_cache_key(self, request: WebSearchRequest) -> str:
        return json.dumps(
            {
                "query": request.query,
                "max_results": request.max_results,
                "region": request.region,
                "safesearch": request.safesearch,
                "time_limit": request.time_limit,
                "backend": self._config.backend,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _get_cached_response(self, cache_key: str) -> WebSearchResponse | None:
        if self._config.cache_seconds <= 0:
            return None

        now = self.context.clock.now()
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._cache[cache_key]
                return None

        return entry.response.model_copy(update={"cached": True})

    def _store_cached_response(self, cache_key: str, response: WebSearchResponse) -> None:
        if self._config.cache_seconds <= 0 or not response.ok:
            return

        expires_at = self.context.clock.now() + timedelta(seconds=self._config.cache_seconds)
        with self._cache_lock:
            self._cache[cache_key] = CacheEntry(expires_at=expires_at, response=response)

    def _search_provider(self, request: WebSearchRequest) -> list[dict[str, Any]]:
        client = self.ddgs_factory(
            self._config.timeout_seconds,
            self.context.http_client_factory.verify,
        )
        try:
            provider_results = client.text(
                request.query,
                region=request.region or self._config.region,
                safesearch=self._map_safesearch(request.safesearch or self._config.safesearch),
                timelimit=request.time_limit,
                max_results=request.max_results,
                backend=self._config.backend,
            )
            return list(provider_results or [])
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _normalize_results(
        self,
        provider_results: list[dict[str, Any]],
        max_results: int,
    ) -> list[WebSearchResult]:
        normalized_results: list[WebSearchResult] = []
        for item in provider_results:
            if len(normalized_results) >= max_results:
                break
            normalized_result = self._normalize_result_item(
                item,
                rank=len(normalized_results) + 1,
            )
            if normalized_result is not None:
                normalized_results.append(normalized_result)
        return normalized_results

    def _normalize_result_item(
        self,
        item: Mapping[str, Any],
        *,
        rank: int,
    ) -> WebSearchResult | None:
        if not isinstance(item, Mapping):
            return None

        title = self._extract_text(item, primary_field="title", fallback_fields=())
        url = self._extract_text(item, primary_field="href", fallback_fields=("url", "link"))
        if title is None or url is None:
            return None

        snippet = self._extract_text(
            item,
            primary_field="body",
            fallback_fields=("snippet", "description"),
        )
        source_value = item.get("source", self._config.backend)
        if not isinstance(source_value, str) or not normalize_text(source_value):
            source_value = self._config.backend

        return WebSearchResult(
            rank=rank,
            title=bound_text(title, max_chars=self._config.result_limits.max_title_chars),
            url=bound_text(url, max_chars=self._config.result_limits.max_url_chars),
            snippet=bound_text(
                snippet or "",
                max_chars=self._config.result_limits.max_snippet_chars,
            ),
            source=bound_text(str(source_value), max_chars=100),
        )

    def _extract_text(
        self,
        item: Mapping[str, Any],
        *,
        primary_field: str,
        fallback_fields: tuple[str, ...],
    ) -> str | None:
        allow_primary = primary_field in self._config.allowed_result_fields
        allow_fallbacks = allow_primary or any(
            field in self._config.allowed_result_fields for field in fallback_fields
        )
        fields_to_check = (primary_field,) + fallback_fields if allow_fallbacks else (primary_field,)

        for field_name in fields_to_check:
            raw_value = item.get(field_name)
            if not isinstance(raw_value, str):
                continue
            normalized = normalize_text(raw_value)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _map_safesearch(value: SafeSearchValue) -> str:
        if value == "strict":
            return "on"
        return value

    def _build_error_response(
        self,
        *,
        request: WebSearchRequest,
        error: WebSearchProviderError,
    ) -> WebSearchResponse:
        return WebSearchResponse.from_error(
            query=request.query,
            provider=self._config.provider,
            backend=self._config.backend,
            region=request.region or self._config.region,
            safesearch=request.safesearch or self._config.safesearch,
            time_limit=request.time_limit,
            max_results=request.max_results,
            error=error,
        )

    @staticmethod
    def _normalize_provider_error(error: Exception) -> WebSearchProviderError:
        error_type = error.__class__.__name__.lower()
        message = normalize_text(str(error))

        if "ddgsexception" in error_type:
            return WebSearchProviderError(
                code="provider_unavailable",
                message="Web search provider is unavailable.",
                retryable=True,
            )

        if isinstance(error, httpx.TimeoutException) or "timeout" in error_type:
            return WebSearchProviderError(
                code="provider_timeout",
                message="Web search provider timed out.",
                retryable=True,
            )

        if isinstance(error, httpx.HTTPError) or isinstance(error, OSError):
            return WebSearchProviderError(
                code="provider_unavailable",
                message="Web search provider is unavailable.",
                retryable=True,
            )

        if "429" in message or "rate" in message.lower():
            return WebSearchProviderError(
                code="provider_rate_limited",
                message="Web search provider rate limited the request.",
                retryable=True,
            )

        return WebSearchProviderError(
            code="provider_error",
            message="Web search provider request failed.",
            retryable=False,
        )