"""Safe public health and profile summaries for the LLM gateway."""

from __future__ import annotations

from app.config.view import LLMSettings
from app.contracts.llm import (
    LLMHealthResult,
    LLMProfileHealthSummary,
    LLMProfileSummary,
    LLMProviderHealthSummary,
)
from app.llm.provider_registry import ProviderRegistry


async def build_health_result(
    *,
    settings: LLMSettings,
    registry: ProviderRegistry,
) -> LLMHealthResult:
    providers: dict[str, LLMProviderHealthSummary] = {}
    profiles: dict[str, LLMProfileHealthSummary] = {}

    for provider_name, provider_settings in settings.providers.items():
        status = "unavailable"
        provider_type = provider_settings.type
        if not provider_settings.enabled:
            status = "disabled"
        elif registry.has(provider_name):
            summary = await registry.get(provider_name, allow_disabled=True).health()
            status = summary.status
            provider_type = summary.provider_type

        providers[provider_name] = LLMProviderHealthSummary(
            status=status,
            type=provider_type,
            enabled=provider_settings.enabled,
        )

    for profile_name, profile_settings in settings.profiles.items():
        provider_status = providers.get(profile_settings.provider)
        status = "ok"
        if not profile_settings.enabled:
            status = "disabled"
        elif provider_status is None or provider_status.status not in {"ok", "degraded"}:
            status = "unavailable"

        profiles[profile_name] = LLMProfileHealthSummary(
            status=status,
            provider=profile_settings.provider,
            enabled=profile_settings.enabled,
            supports_streaming=profile_settings.supports_streaming,
        )

    return LLMHealthResult(
        status=_overall_status(providers=providers, profiles=profiles),
        providers_configured=bool(settings.providers),
        profiles_configured=bool(settings.profiles),
        default_profile=settings.defaults.profile,
        providers=providers,
        profiles=profiles,
    )


def build_profile_summaries(settings: LLMSettings) -> list[LLMProfileSummary]:
    summaries: list[LLMProfileSummary] = []
    for profile_name, profile in settings.profiles.items():
        summaries.append(
            LLMProfileSummary(
                name=profile_name,
                provider=profile.provider,
                model=profile.model,
                enabled=profile.enabled,
                supports_streaming=profile.supports_streaming,
                supports_json_schema=profile.supports_json_schema,
                supports_tool_calling=profile.supports_tool_calling,
                fallback_profiles=profile.fallback_profiles,
                allowed_for={
                    "usecases": profile.allowed_for.usecases,
                    "agents": profile.allowed_for.agents,
                    "strategies": profile.allowed_for.strategies,
                },
                metadata=dict(profile.extra),
            )
        )
    return summaries


def _overall_status(
    *,
    providers: dict[str, LLMProviderHealthSummary],
    profiles: dict[str, LLMProfileHealthSummary],
) -> str:
    if not providers or not profiles:
        return "unavailable"
    if any(summary.status == "ok" for summary in providers.values()) and any(
        summary.status == "ok" for summary in profiles.values()
    ):
        return "ok"
    if any(summary.status == "degraded" for summary in providers.values()):
        return "degraded"
    return "unavailable"