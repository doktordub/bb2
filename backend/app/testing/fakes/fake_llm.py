"""In-memory fake LLM gateway for contract-focused tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMRequest, LLMResponse, LLMStreamDelta


class FakeLLMGateway:
    """Deterministic LLM fake that records requests."""

    def __init__(self, response_text: str = "fake response") -> None:
        self.response_text = response_text
        self.requests: list[LLMRequest] = []
        self.contexts: list[OrchestrationContext] = []

    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        self.requests.append(request)
        self.contexts.append(context)
        return LLMResponse(
            text=self.response_text,
            profile=request.profile or "fake_profile",
            provider="fake_provider",
            model="fake_model",
        )

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamDelta]:
        self.requests.append(request)
        self.contexts.append(context)
        yield LLMStreamDelta(
            text_delta=self.response_text,
            profile=request.profile or "fake_profile",
            provider="fake_provider",
            model="fake_model",
            is_final=True,
        )