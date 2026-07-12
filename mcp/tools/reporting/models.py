"""Typed configuration models for the reporting MCP plugin."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.errors import MCPToolConfigurationError
from app.tools_base.dataset_models import MetricGranularity


FixtureDatasetName = Literal[
    "monthly_income_expense",
    "truncated_result",
    "empty_result",
    "invalid_numeric_result",
]
ReportingProviderName = Literal["fixture"]
HealthcheckMode = Literal["safe", "provider"]


class ReportingToolConfig(BaseModel):
    """Resolved runtime configuration for the reporting plugin."""

    model_config = ConfigDict(extra="ignore")

    provider: ReportingProviderName = "fixture"
    fixture_dataset: FixtureDatasetName = "monthly_income_expense"
    enabled_metrics: list[str] = Field(
        default_factory=lambda: ["income", "expense"],
        min_length=1,
        max_length=5,
    )
    enabled_dimensions: list[str] = Field(
        default_factory=lambda: ["reporting_period"],
        min_length=1,
        max_length=5,
    )
    max_date_range_days: int = Field(default=730, ge=1, le=3650)
    default_granularity: MetricGranularity = "month"
    maximum_rows: int = Field(default=24, ge=1, le=100)
    maximum_metrics_per_query: int = Field(default=3, ge=1, le=5)
    maximum_filters: int = Field(default=5, ge=0, le=10)
    max_result_bytes: int = Field(default=262144, ge=256, le=1048576)
    timeout_seconds: int = Field(default=20, ge=1, le=60)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=3600)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    retry_attempts: int = Field(default=2, ge=1, le=4)
    circuit_breaker_threshold: int = Field(default=3, ge=1, le=20)
    circuit_breaker_reset_seconds: int = Field(default=60, ge=5, le=900)
    provider_auth_profile: str = Field(default="none", min_length=1, max_length=64)
    healthcheck_mode: HealthcheckMode = "safe"

    @field_validator("enabled_metrics", "enabled_dimensions", mode="before")
    @classmethod
    def normalize_identifier_lists(cls, value: Any) -> Any:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return value

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)
                continue

            cleaned = item.strip()
            if not cleaned:
                raise ValueError("identifier lists must not contain blank values.")
            lowered = cleaned.lower()
            if lowered in seen:
                raise ValueError(f"duplicate identifier {cleaned!r} is not allowed.")
            normalized.append(cleaned)
            seen.add(lowered)

        return normalized

    @field_validator("provider_auth_profile", mode="before")
    @classmethod
    def normalize_auth_profile(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("provider_auth_profile must not be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_provider_constraints(self) -> "ReportingToolConfig":
        if self.provider == "fixture" and self.provider_auth_profile.lower() != "none":
            raise ValueError("fixture reporting provider must use provider_auth_profile='none'.")
        return self

    @property
    def auth_profile_configured(self) -> bool:
        return self.provider_auth_profile.lower() != "none"


def load_reporting_tool_config(raw_config: dict[str, Any]) -> ReportingToolConfig:
    """Validate and return the resolved reporting plugin configuration."""

    try:
        return ReportingToolConfig.model_validate(raw_config)
    except ValidationError as error:
        raise MCPToolConfigurationError(
            f"Invalid reporting tool configuration: {error}"
        ) from error
