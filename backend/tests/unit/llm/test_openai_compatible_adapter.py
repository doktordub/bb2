from __future__ import annotations

import json

import httpx
import pytest

from app.config.view import LLMProfileAllowlistSettings, LLMProfileSettings, LLMProviderSettings
from app.contracts.llm import LLMMessage, LLMRequest, LLMResponseFormat
from app.llm.errors import LLMProviderTimeoutError
from app.llm.models import ResolvedLLMRequest
from app.llm.providers.openai_compatible import OpenAICompatibleProviderAdapter


def _build_provider() -> LLMProviderSettings:
    return LLMProviderSettings(
        name="local_provider",
        type="openai_compatible",
        enabled=True,
        base_url="http://localhost:8081/v1",
        endpoint=None,
        api_key="secret-token",
        auth_header=None,
        auth_token=None,
        timeout_seconds=30,
        stream_timeout_seconds=60,
        headers={"X-Client": "pytest"},
        extra={},
    )


def _build_resolved_request() -> ResolvedLLMRequest:
    provider = _build_provider()
    profile = LLMProfileSettings(
        name="local_reasoning",
        enabled=True,
        provider="local_provider",
        model="local-model",
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=256,
        max_input_tokens=None,
        max_total_tokens=None,
        timeout_seconds=None,
        stream_timeout_seconds=None,
        supports_streaming=True,
        supports_json_schema=True,
        supports_tool_calling=False,
        allowed_for=LLMProfileAllowlistSettings(
            usecases=("default_chat",),
            agents=("support_agent",),
            strategies=("direct_agent",),
        ),
        fallback_profiles=(),
        extra={},
    )
    request = LLMRequest(
        component="agent.support_agent",
        messages=[LLMMessage(role="user", content="Explain the gateway path")],
        response_format=LLMResponseFormat(
            type="json_schema",
            schema_name="answer",
            json_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
            strict=True,
        ),
    )
    return ResolvedLLMRequest(
        request=request,
        defaults=type("Defaults", (), {
            "profile": "local_reasoning",
            "timeout_seconds": 30,
            "stream_timeout_seconds": 60,
            "max_retries": 1,
            "trace_prompts": False,
            "trace_completions": False,
        })(),
        provider=provider,
        profile=profile,
        profile_name="local_reasoning",
        provider_name="local_provider",
        model="local-model",
        timeout_seconds=30,
        stream_timeout_seconds=60,
        max_retries=1,
        response_format=request.response_format,
        max_output_tokens=256,
        agent_name="support_agent",
        strategy_name="direct_agent",
        usecase_name="default_chat",
    )


@pytest.mark.asyncio
async def test_openai_compatible_complete_maps_request_and_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "cmpl-123",
                "model": "local-model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "gateway answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(_build_provider(), client=client)

    response = await adapter.complete(_build_resolved_request())

    await client.aclose()

    assert captured["url"] == "http://localhost:8081/v1/chat/completions"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer secret-token"
    assert headers["x-client"] == "pytest"

    request_json = captured["json"]
    assert isinstance(request_json, dict)
    assert request_json["model"] == "local-model"
    assert request_json["stream"] is False
    assert request_json["messages"] == [{"role": "user", "content": "Explain the gateway path"}]
    assert request_json["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "answer",
            "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
            "strict": True,
        },
    }

    assert response.text == "gateway answer"
    assert response.finish_reason == "completed"
    assert response.raw_id == "cmpl-123"
    assert response.usage is not None
    assert response.usage.total_tokens == 15
    assert response.metadata == {"response_id": "cmpl-123", "model": "local-model"}


@pytest.mark.asyncio
async def test_openai_compatible_complete_maps_timeout_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(_build_provider(), client=client)

    with pytest.raises(LLMProviderTimeoutError, match="timed out"):
        await adapter.complete(_build_resolved_request())

    await client.aclose()


@pytest.mark.asyncio
async def test_openai_compatible_provider_accepts_host_only_base_url() -> None:
    captured: dict[str, object] = {}

    provider = LLMProviderSettings(
        name="local_provider",
        type="openai_compatible",
        enabled=True,
        base_url="http://192.168.1.80:8081",
        endpoint=None,
        api_key="secret-token",
        auth_header=None,
        auth_token=None,
        timeout_seconds=30,
        stream_timeout_seconds=60,
        headers={"X-Client": "pytest"},
        extra={},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "id": "cmpl-456",
                "model": "local-model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "gateway answer"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(provider, client=client)

    await adapter.complete(_build_resolved_request())

    await client.aclose()

    assert captured["url"] == "http://192.168.1.80:8081/v1/chat/completions"