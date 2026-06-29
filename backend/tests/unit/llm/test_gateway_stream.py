from __future__ import annotations

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMStreamingError
from app.llm.providers import FakeLLMProviderAdapter
from tests.unit.llm.support import base_config, build_context, build_gateway, build_registry


async def test_gateway_stream_yields_lifecycle_events() -> None:
    config = base_config()
    registry = build_registry(
        config,
        primary_adapter=FakeLLMProviderAdapter(
            name="primary_provider",
            stream_chunks=("hello ", "world"),
        ),
    )
    gateway = build_gateway(config, registry=registry)
    context = build_context(config)

    events = [
        event
        async for event in gateway.stream(
            LLMRequest(messages=[LLMMessage(role="user", content="hello world")], stream=True),
            context,
        )
    ]

    assert [event.type for event in events] == ["started", "delta", "delta", "completed"]
    assert events[0].profile == "primary_profile"
    assert events[1].text == "hello "
    assert events[2].text == "world"
    assert events[3].finish_reason == "completed"


async def test_gateway_stream_emits_error_event_after_partial_output() -> None:
    config = base_config()

    class PartialFailureProvider(FakeLLMProviderAdapter):
        async def stream(self, request):  # type: ignore[override]
            yield type(self).started_event()
            yield type(self).delta_event("partial ")
            raise LLMStreamingError("stream failed")

        @staticmethod
        def started_event():
            from app.llm.models import ProviderLLMStreamEvent

            return ProviderLLMStreamEvent.started()

        @staticmethod
        def delta_event(text: str):
            from app.llm.models import ProviderLLMStreamEvent

            return ProviderLLMStreamEvent.delta(text=text)

    registry = build_registry(
        config,
        primary_adapter=PartialFailureProvider(name="primary_provider"),
    )
    gateway = build_gateway(config, registry=registry)
    context = build_context(config)

    events = [
        event
        async for event in gateway.stream(
            LLMRequest(messages=[LLMMessage(role="user", content="hello world")], stream=True),
            context,
        )
    ]

    assert [event.type for event in events] == ["started", "delta", "error"]
    assert events[-1].error is not None
    assert events[-1].error.code == "llm_streaming_error"