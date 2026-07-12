"""In-memory fake LLM gateway for contract-focused tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.llm import (
    LLMHealthResult,
    LLMProfileHealthSummary,
    LLMProfileSummary,
    LLMProviderHealthSummary,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMTokenUsage,
    LLMToolCall,
)


class FakeLLMGateway:
    """Deterministic LLM fake that records requests."""

    def __init__(
        self,
        response_text: str = "fake response",
        *,
        default_profile: str = "fake_profile",
        tool_calls: Sequence[LLMToolCall | Mapping[str, Any]] | None = None,
        reasoning: Mapping[str, Any] | None = None,
        supports_tool_calling: bool = False,
    ) -> None:
        self.response_text = response_text
        self.default_profile = default_profile
        self.provider_name = "fake_provider"
        self.model_name = "fake_model"
        self.tool_calls = [
            item if isinstance(item, LLMToolCall) else LLMToolCall.from_mapping(item)
            for item in (tool_calls or ())
        ]
        self.reasoning = dict(reasoning or {})
        self.supports_tool_calling = supports_tool_calling or bool(self.tool_calls)
        self.requests: list[LLMRequest] = []
        self.contexts: list[OrchestrationContext] = []
        self.health_calls = 0
        self.list_profiles_calls = 0

    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        self.requests.append(request)
        self.contexts.append(context)
        profile = request.profile or self.default_profile
        return LLMResponse(
            text=self.response_text,
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            tool_calls=list(self.tool_calls),
            finish_reason="completed",
            reasoning=dict(self.reasoning),
            usage=LLMTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            metadata={"component": request.component} if request.component else {},
        )

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamEvent]:
        self.requests.append(request)
        self.contexts.append(context)
        profile = request.profile or self.default_profile
        metadata = {"component": request.component} if request.component else {}
        yield LLMStreamEvent.started(
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            metadata=metadata,
        )
        if self.response_text:
            yield LLMStreamEvent.delta(
                text=self.response_text,
                profile=profile,
                provider=self.provider_name,
                model=self.model_name,
            )
        yield LLMStreamEvent.completed(
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            tool_calls=list(self.tool_calls),
            finish_reason="completed",
            reasoning=dict(self.reasoning),
            usage=LLMTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )

    async def health(self) -> LLMHealthResult:
        self.health_calls += 1
        return LLMHealthResult(
            status="ok",
            providers_configured=True,
            profiles_configured=True,
            default_profile=self.default_profile,
            providers={
                self.provider_name: LLMProviderHealthSummary(
                    status="ok",
                    type="fake",
                    enabled=True,
                )
            },
            profiles={
                self.default_profile: LLMProfileHealthSummary(
                    status="ok",
                    provider=self.provider_name,
                    enabled=True,
                    supports_streaming=True,
                )
            },
        )

    async def list_profiles(self) -> list[LLMProfileSummary]:
        self.list_profiles_calls += 1
        return [
            LLMProfileSummary(
                name=self.default_profile,
                provider=self.provider_name,
                model=self.model_name,
                enabled=True,
                supports_streaming=True,
                supports_json_schema=False,
                supports_tool_calling=self.supports_tool_calling,
                fallback_profiles=(),
                allowed_for={},
                metadata={"source": "fake"},
            )
        ]