"""Factory helpers for assembling the concrete backend LLM runtime stack."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from typing import Any

from app.config.view import LLMProviderSettings, get_llm_settings
from app.contracts.config import ConfigurationView
from app.contracts.policy import PolicyService
from app.llm.provider_base import LLMProviderAdapter
from app.llm.gateway import DefaultLLMGateway
from app.llm.profile_resolver import LLMProfileResolver
from app.llm.provider_registry import ProviderRegistry
from app.llm.providers import (
    CustomHttpProviderAdapter,
    FakeLLMProviderAdapter,
    GoogleProviderAdapter,
    OpenAICompatibleProviderAdapter,
    OpenAIProviderAdapter,
)
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder


@dataclass(frozen=True, slots=True)
class LLMRuntimeBundle:
    """Composed LLM runtime services for startup wiring and tests."""

    registry: ProviderRegistry
    policy_service: PolicyService
    profile_resolver: LLMProfileResolver
    gateway: DefaultLLMGateway


def build_llm_runtime(
    config: ConfigurationView,
    *,
    policy_service: PolicyService,
    metrics: MetricsRecorder | None = None,
    logger: logging.Logger | None = None,
) -> LLMRuntimeBundle:
    """Build the concrete provider registry, policy service, resolver, and gateway."""

    settings = get_llm_settings(config)
    registry = ProviderRegistry(settings.providers)
    for provider_name, provider in settings.providers.items():
        registry.register(provider_name, _build_provider_adapter(provider))

    profile_resolver = LLMProfileResolver()
    gateway = DefaultLLMGateway(
        config=config,
        registry=registry,
        profile_resolver=profile_resolver,
        policy_service=policy_service,
        metrics=metrics or NoopMetricsRecorder(),
        logger=logger,
    )
    return LLMRuntimeBundle(
        registry=registry,
        policy_service=policy_service,
        profile_resolver=profile_resolver,
        gateway=gateway,
    )


def _build_provider_adapter(provider: LLMProviderSettings) -> LLMProviderAdapter:
    if provider.type == "fake":
        return FakeLLMProviderAdapter(
            name=provider.name,
            provider_type=provider.type,
            response_text=_read_response_text(provider.extra),
            stream_chunks=_read_stream_chunks(provider.extra),
            health_status=_read_str(provider.extra.get("health_status")) or "ok",
            enabled=provider.enabled,
            supports_streaming=_read_bool(provider.extra.get("supports_streaming"), True),
            supports_json_schema=_read_bool(provider.extra.get("supports_json_schema"), True),
            supports_tool_calling=_read_bool(provider.extra.get("supports_tool_calling"), False),
        )
    if provider.type == "openai_compatible":
        return OpenAICompatibleProviderAdapter(provider)
    if provider.type == "openai":
        return OpenAIProviderAdapter(provider)
    if provider.type == "google":
        return GoogleProviderAdapter(provider)
    if provider.type == "custom_http":
        return CustomHttpProviderAdapter(provider)
    raise ValueError(f"Unsupported LLM provider type: {provider.type}")


def _read_response_text(extra: dict[str, Any]) -> str:
    value = _read_str(extra.get("response_text"))
    if value is not None:
        return value
    return "fake response"


def _read_stream_chunks(extra: dict[str, Any]) -> Sequence[str] | None:
    value = extra.get("stream_chunks")
    if not isinstance(value, list):
        return None
    chunks: list[str] = []
    for item in value:
        if isinstance(item, str):
            chunks.append(item)
    return tuple(chunks) if chunks else None


def _read_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default