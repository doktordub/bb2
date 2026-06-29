"""Helpers for normalizing provider stream events into gateway events."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts.llm import LLMStreamEvent, LLMTokenUsage
from app.llm.models import ProviderLLMStreamEvent, ResolvedLLMRequest


@dataclass(slots=True)
class StreamAssembly:
    """Collected stream state used by the gateway during streaming calls."""

    text_parts: list[str] = field(default_factory=list)
    usage: LLMTokenUsage | None = None
    finish_reason: str | None = None

    @property
    def text(self) -> str:
        return "".join(self.text_parts)


def normalize_stream_event(
    *,
    event: ProviderLLMStreamEvent,
    resolved: ResolvedLLMRequest,
) -> LLMStreamEvent:
    if event.type == "started":
        return LLMStreamEvent.started(
            profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            metadata=dict(event.metadata),
        )
    if event.type == "delta":
        return LLMStreamEvent.delta(
            text=event.text or "",
            profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            metadata=dict(event.metadata),
        )
    if event.type == "metadata":
        return LLMStreamEvent(
            type="metadata",
            profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            metadata=dict(event.metadata),
        )
    return LLMStreamEvent.completed(
        profile=resolved.profile_name,
        provider=resolved.provider_name,
        model=resolved.model,
        finish_reason=event.finish_reason,
        usage=event.usage,
        metadata=dict(event.metadata),
    )


def update_stream_assembly(*, event: ProviderLLMStreamEvent, assembly: StreamAssembly) -> None:
    if event.type == "delta" and event.text:
        assembly.text_parts.append(event.text)
    if event.usage is not None:
        assembly.usage = event.usage
    if event.finish_reason is not None:
        assembly.finish_reason = event.finish_reason