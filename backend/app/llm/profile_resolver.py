"""Configuration-driven LLM profile resolution."""

from __future__ import annotations

from collections.abc import Iterable

from app.config.view import get_llm_settings
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMRequest, LLMResponseFormat
from app.llm.errors import (
    LLMProfileResolutionError,
    LLMProviderUnavailableError,
    LLMUnsupportedCapabilityError,
)
from app.llm.models import ResolvedLLMRequest


class LLMProfileResolver:
    """Resolve a provider-neutral LLM request into one concrete logical profile."""

    def resolve(
        self,
        *,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> ResolvedLLMRequest:
        settings = get_llm_settings(context.config)

        agent_name = _read_name(request=request, context=context, key="agent_name")
        strategy_name = _read_name(request=request, context=context, key="strategy_name")
        usecase_name = context.request.usecase or _read_optional_str(context.config.get("app.active_usecase"))

        candidates = tuple(
            _dedupe_candidates(
                [
                    _candidate(request.profile, "request"),
                    _candidate(_lookup_named_profile(context, section="agents", name=agent_name), "agent"),
                    _candidate(
                        _lookup_named_profile(context, section="strategies", name=strategy_name),
                        "strategy",
                    ),
                    _candidate(
                        _lookup_orchestrator_profile(context, usecase_name=usecase_name),
                        "usecase",
                    ),
                    _candidate(settings.defaults.profile, "default"),
                ]
            )
        )

        for profile_name, source in candidates:
            profile = settings.profiles.get(profile_name)
            if profile is None:
                if source == "request":
                    raise LLMProfileResolutionError(
                        f"Requested LLM profile '{profile_name}' is not defined.",
                        metadata={"profile": profile_name},
                    )
                continue
            if not profile.enabled:
                raise LLMProfileResolutionError(
                    f"Resolved LLM profile '{profile_name}' is disabled.",
                    metadata={"profile": profile_name, "source": source},
                )

            provider = settings.providers.get(profile.provider)
            if provider is None or not provider.enabled:
                raise LLMProviderUnavailableError(
                    f"Resolved LLM provider '{profile.provider}' is unavailable.",
                    metadata={"profile": profile_name, "provider": profile.provider},
                )

            raw_response_format = request.response_format
            if raw_response_format is None:
                response_format = None
            elif isinstance(raw_response_format, LLMResponseFormat):
                response_format = raw_response_format
            else:
                response_format = LLMResponseFormat.from_mapping(raw_response_format)
            if response_format is not None and response_format.type != "text" and not profile.supports_json_schema:
                raise LLMUnsupportedCapabilityError(
                    f"LLM profile '{profile_name}' does not support structured output.",
                    metadata={"profile": profile_name, "response_format": response_format.type},
                )

            if request.stream and not profile.supports_streaming:
                raise LLMUnsupportedCapabilityError(
                    f"LLM profile '{profile_name}' does not support streaming.",
                    metadata={"profile": profile_name},
                )

            return ResolvedLLMRequest(
                request=request,
                defaults=settings.defaults,
                provider=provider,
                profile=profile,
                profile_name=profile_name,
                provider_name=provider.name,
                model=profile.model,
                timeout_seconds=request.timeout_seconds or profile.timeout_seconds or provider.timeout_seconds or settings.defaults.timeout_seconds,
                stream_timeout_seconds=profile.stream_timeout_seconds or provider.stream_timeout_seconds or settings.defaults.stream_timeout_seconds,
                max_retries=settings.defaults.max_retries,
                response_format=response_format,
                max_output_tokens=request.max_output_tokens or profile.max_output_tokens,
                agent_name=agent_name,
                strategy_name=strategy_name,
                usecase_name=usecase_name,
                resolution_source=source,
                metadata={"profile": profile_name, "source": source},
            )

        raise LLMProfileResolutionError("No enabled LLM profile could be resolved.")


def _candidate(value: str | None, source: str) -> tuple[str, str] | None:
    if value is None:
        return None
    return value, source


def _dedupe_candidates(
    candidates: Iterable[tuple[str, str] | None],
) -> Iterable[tuple[str, str]]:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        profile_name, source = candidate
        if profile_name in seen:
            continue
        seen.add(profile_name)
        yield profile_name, source


def _lookup_named_profile(
    context: OrchestrationContext,
    *,
    section: str,
    name: str | None,
) -> str | None:
    if name is None:
        return None
    value = context.config.get(f"{section}.{name}.llm_profile")
    return _read_optional_str(value)


def _lookup_orchestrator_profile(
    context: OrchestrationContext,
    *,
    usecase_name: str | None,
) -> str | None:
    if usecase_name is None:
        return None
    value = context.config.get(f"usecases.{usecase_name}.orchestrator_llm_profile")
    return _read_optional_str(value)


def _read_name(
    *,
    request: LLMRequest,
    context: OrchestrationContext,
    key: str,
) -> str | None:
    request_value = _read_optional_str(request.metadata.get(key))
    if request_value is not None:
        return request_value
    return _read_optional_str(context.runtime_metadata.get(key))


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None