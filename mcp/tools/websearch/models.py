"""Pydantic models for the websearch MCP tool."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SafeSearchValue = Literal["off", "moderate", "strict"]
TimeLimitValue = Literal["d", "w", "m", "y"]
ProviderName = Literal["ddgs"]


def normalize_text(value: str) -> str:
    """Collapse repeated whitespace and strip surrounding spaces."""

    return " ".join(value.split()).strip()


def bound_text(value: str, *, max_chars: int) -> str:
    """Normalize and truncate free-form provider text to a safe bound."""

    normalized = normalize_text(value)
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return normalized[:max_chars]
    return normalized[: max_chars - 3].rstrip() + "..."


class StrictWebSearchModel(BaseModel):
    """Base model for strict request and response validation."""

    model_config = ConfigDict(extra="forbid")


class WebSearchResultLimits(StrictWebSearchModel):
    """Configured maximum sizes for normalized provider results."""

    max_title_chars: int = Field(default=200, ge=1, le=500)
    max_url_chars: int = Field(default=1000, ge=1, le=2000)
    max_snippet_chars: int = Field(default=500, ge=1, le=2000)
    max_results: int = Field(default=10, ge=1, le=25)


class WebSearchToolConfig(BaseModel):
    """Resolved runtime configuration for the websearch plugin."""

    model_config = ConfigDict(extra="ignore")

    provider: ProviderName = "ddgs"
    backend: str = Field(default="duckduckgo", min_length=1, max_length=50)
    region: str = Field(default="us-en", min_length=2, max_length=32)
    safesearch: SafeSearchValue = "moderate"
    time_limit: TimeLimitValue | None = None
    max_results: int = Field(default=10, ge=1, le=25)
    max_query_chars: int = Field(default=500, ge=1, le=500)
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    cache_seconds: int = Field(default=300, ge=0, le=3600)
    allowed_result_fields: list[str] = Field(
        default_factory=lambda: ["title", "href", "body"],
        min_length=1,
        max_length=10,
    )
    result_limits: WebSearchResultLimits = Field(default_factory=WebSearchResultLimits)
    deep_healthcheck: bool = False

    @field_validator("backend", "region", mode="before")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("tool configuration fields must not be blank.")
        return normalized

    @field_validator("allowed_result_fields")
    @classmethod
    def validate_allowed_result_fields(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = normalize_text(item)
            if not cleaned:
                raise ValueError("allowed_result_fields must not contain blank values.")
            if cleaned not in seen:
                normalized.append(cleaned)
                seen.add(cleaned)

        if "title" not in seen:
            raise ValueError("allowed_result_fields must include title.")
        if not ({"href", "url"} & seen):
            raise ValueError("allowed_result_fields must include href or url.")
        return normalized

    @model_validator(mode="after")
    def validate_effective_limits(self) -> "WebSearchToolConfig":
        if self.max_results > self.result_limits.max_results:
            raise ValueError("max_results must not exceed result_limits.max_results.")
        return self


class WebSearchRequest(StrictWebSearchModel):
    """Validated tool input for public web text search."""

    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=25)
    region: str | None = Field(default=None, min_length=2, max_length=32)
    safesearch: SafeSearchValue | None = None
    time_limit: TimeLimitValue | None = None

    @field_validator("query", mode="before")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("query must not be blank.")
        return normalized

    @field_validator("region", mode="before")
    @classmethod
    def validate_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_text(value)
        return normalized or None


class WebSearchResult(StrictWebSearchModel):
    """One bounded normalized search result."""

    rank: int = Field(ge=1, le=25)
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    snippet: str = Field(default="", max_length=500)
    source: str = Field(min_length=1, max_length=100)

    @field_validator("title", "url", "snippet", "source", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: str) -> str:
        return normalize_text(value)


class WebSearchProviderError(StrictWebSearchModel):
    """Safe normalized provider error returned to callers."""

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=300)
    retryable: bool = False

    @field_validator("code", "message", mode="before")
    @classmethod
    def normalize_error_fields(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("error fields must not be blank.")
        return normalized


class WebSearchResponse(StrictWebSearchModel):
    """Structured response returned by the websearch tool."""

    ok: bool = True
    query: str = Field(min_length=1, max_length=500)
    provider: ProviderName = "ddgs"
    backend: str = Field(min_length=1, max_length=50)
    region: str = Field(min_length=2, max_length=32)
    safesearch: SafeSearchValue
    time_limit: TimeLimitValue | None = None
    max_results: int = Field(ge=1, le=25)
    result_count: int = Field(ge=0, le=25)
    results: list[WebSearchResult] = Field(default_factory=list, max_length=25)
    cached: bool = False
    error: WebSearchProviderError | None = None

    @field_validator("query", "backend", "region", mode="before")
    @classmethod
    def normalize_response_text(cls, value: str) -> str:
        return normalize_text(value)

    @model_validator(mode="after")
    def validate_response(self) -> "WebSearchResponse":
        if self.result_count != len(self.results):
            raise ValueError("result_count must match the number of results.")
        if len(self.results) > self.max_results:
            raise ValueError("results must not exceed max_results.")
        if self.ok and self.error is not None:
            raise ValueError("successful responses must not include an error.")
        if not self.ok and self.error is None:
            raise ValueError("failed responses must include an error.")
        if not self.ok and self.results:
            raise ValueError("failed responses must not include results.")
        return self

    @classmethod
    def from_error(
        cls,
        *,
        query: str,
        provider: ProviderName,
        backend: str,
        region: str,
        safesearch: SafeSearchValue,
        time_limit: TimeLimitValue | None,
        max_results: int,
        error: WebSearchProviderError,
    ) -> "WebSearchResponse":
        return cls(
            ok=False,
            query=query,
            provider=provider,
            backend=backend,
            region=region,
            safesearch=safesearch,
            time_limit=time_limit,
            max_results=max_results,
            result_count=0,
            results=[],
            cached=False,
            error=error,
        )