"""In-memory fake LLM gateway for contract-focused tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

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
)


class FakeLLMGateway:
    """Deterministic LLM fake that records requests."""

    def __init__(
        self,
        response_text: str = "fake response",
        *,
        default_profile: str = "fake_profile",
    ) -> None:
        self.response_text = response_text
        self.default_profile = default_profile
        self.provider_name = "fake_provider"
        self.model_name = "fake_model"
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
            finish_reason="completed",
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
            finish_reason="completed",
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
                supports_tool_calling=False,
                fallback_profiles=(),
                allowed_for={},
                metadata={"source": "fake"},
            )
        ]