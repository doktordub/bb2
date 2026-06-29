"""Deterministic fake provider adapter for LLM gateway development and tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from app.contracts.llm import LLMTokenUsage
from app.llm.errors import LLMProviderUnavailableError
from app.llm.models import (
    ProviderCapabilities,
    ProviderHealthSummary,
    ProviderLLMResponse,
    ProviderLLMStreamEvent,
    ResolvedLLMRequest,
)


@dataclass(frozen=True, slots=True)
class FakeProviderCall:
    """Recorded provider invocation used by focused LLM runtime tests."""

    request: ResolvedLLMRequest
    mode: str


class FakeLLMProviderAdapter:
    """Simple in-memory provider adapter that emits deterministic responses."""

    def __init__(
        self,
        *,
        name: str = "fake_provider",
        provider_type: str = "fake",
        response_text: str = "fake response",
        stream_chunks: Sequence[str] | None = None,
        complete_errors: Sequence[Exception] | None = None,
        stream_errors: Sequence[Exception] | None = None,
        health_status: str = "ok",
        enabled: bool = True,
        supports_streaming: bool = True,
        supports_json_schema: bool = True,
        supports_tool_calling: bool = False,
    ) -> None:
        self.name = name
        self.provider_type = provider_type
        self.response_text = response_text
        self.stream_chunks = tuple(stream_chunks) if stream_chunks is not None else (response_text,)
        self._complete_errors = list(complete_errors or [])
        self._stream_errors = list(stream_errors or [])
        self._health_status = health_status
        self._enabled = enabled
        self.capabilities = ProviderCapabilities(
            provider_name=name,
            provider_type=provider_type,
            supports_streaming=supports_streaming,
            supports_json_schema=supports_json_schema,
            supports_tool_calling=supports_tool_calling,
        )
        self.calls: list[FakeProviderCall] = []

    async def complete(self, request: ResolvedLLMRequest) -> ProviderLLMResponse:
        self.calls.append(FakeProviderCall(request=request, mode="complete"))
        self._raise_if_disabled()
        if self._complete_errors:
            raise self._complete_errors.pop(0)
        return ProviderLLMResponse(
            text=self.response_text,
            finish_reason="completed",
            usage=LLMTokenUsage(
                input_tokens=max(len(request.request.messages), 1),
                output_tokens=max(len(self.response_text.split()), 1),
                total_tokens=max(len(request.request.messages), 1) + max(len(self.response_text.split()), 1),
            ),
            raw_id=f"{self.name}-response",
            metadata={"provider_type": self.provider_type},
        )

    async def stream(self, request: ResolvedLLMRequest) -> AsyncIterator[ProviderLLMStreamEvent]:
        self.calls.append(FakeProviderCall(request=request, mode="stream"))
        self._raise_if_disabled()
        if self._stream_errors:
            raise self._stream_errors.pop(0)

        yield ProviderLLMStreamEvent.started()
        for chunk in self.stream_chunks:
            yield ProviderLLMStreamEvent.delta(text=chunk)
        yield ProviderLLMStreamEvent.completed(
            finish_reason="completed",
            usage=LLMTokenUsage(
                input_tokens=max(len(request.request.messages), 1),
                output_tokens=max(sum(len(chunk.split()) for chunk in self.stream_chunks), 1),
                total_tokens=max(len(request.request.messages), 1)
                + max(sum(len(chunk.split()) for chunk in self.stream_chunks), 1),
            ),
        )

    async def health(self) -> ProviderHealthSummary:
        return ProviderHealthSummary(
            provider_name=self.name,
            provider_type=self.provider_type,
            status=self._health_status,
            enabled=self._enabled,
            available=self._enabled and self._health_status in {"ok", "degraded"},
            metadata={"source": "fake"},
        )

    def _raise_if_disabled(self) -> None:
        if not self._enabled:
            raise LLMProviderUnavailableError(
                f"LLM provider '{self.name}' is disabled.",
                metadata={"provider": self.name},
            )