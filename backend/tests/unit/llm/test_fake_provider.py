from __future__ import annotations

from app.config.view import LLMDefaultsSettings, LLMProfileAllowlistSettings, LLMProfileSettings, LLMProviderSettings
from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.models import ResolvedLLMRequest
from app.llm.providers import FakeLLMProviderAdapter


def build_resolved_request(*, stream: bool = False) -> ResolvedLLMRequest:
    return ResolvedLLMRequest(
        request=LLMRequest(
            messages=[LLMMessage(role="user", content="hello")],
            stream=stream,
        ),
        defaults=LLMDefaultsSettings(
            profile="fake_profile",
            timeout_seconds=10,
            stream_timeout_seconds=20,
            max_retries=1,
            trace_prompts=False,
            trace_completions=False,
        ),
        provider=LLMProviderSettings(
            name="fake_provider",
            type="fake",
            enabled=True,
            base_url=None,
            endpoint=None,
            api_key=None,
            auth_header=None,
            auth_token=None,
            timeout_seconds=10,
            stream_timeout_seconds=20,
            headers={},
            extra={},
        ),
        profile=LLMProfileSettings(
            name="fake_profile",
            enabled=True,
            provider="fake_provider",
            model="fake-model",
            temperature=None,
            top_p=None,
            max_output_tokens=128,
            max_input_tokens=None,
            max_total_tokens=None,
            timeout_seconds=None,
            stream_timeout_seconds=None,
            supports_streaming=True,
            supports_json_schema=True,
            supports_tool_calling=False,
            allowed_for=LLMProfileAllowlistSettings(usecases=(), agents=(), strategies=()),
            fallback_profiles=(),
            extra={},
        ),
        profile_name="fake_profile",
        provider_name="fake_provider",
        model="fake-model",
        timeout_seconds=10,
        stream_timeout_seconds=20,
        max_retries=1,
        response_format=None,
        max_output_tokens=128,
    )


async def test_fake_provider_returns_deterministic_completion() -> None:
    adapter = FakeLLMProviderAdapter(response_text="provider answer")

    response = await adapter.complete(build_resolved_request())

    assert response.text == "provider answer"
    assert response.finish_reason == "completed"
    assert response.usage is not None
    assert response.raw_id == "fake_provider-response"


async def test_fake_provider_streams_started_delta_completed_events() -> None:
    adapter = FakeLLMProviderAdapter(stream_chunks=("hello ", "world"))

    events = [event async for event in adapter.stream(build_resolved_request(stream=True))]

    assert [event.type for event in events] == ["started", "delta", "delta", "completed"]
    assert events[1].text == "hello "
    assert events[2].text == "world"
    assert events[3].usage is not None


async def test_fake_provider_health_is_safe_and_provider_owned() -> None:
    adapter = FakeLLMProviderAdapter(name="local_fake", health_status="degraded")

    health = await adapter.health()

    assert health.provider_name == "local_fake"
    assert health.provider_type == "fake"
    assert health.status == "degraded"
    assert health.metadata == {"source": "fake"}