from __future__ import annotations

import httpx
import pytest

from app.config.view import LLMProfileAllowlistSettings, LLMProfileSettings, LLMProviderSettings
from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.models import ResolvedLLMRequest
from app.llm.providers.openai_compatible import OpenAICompatibleProviderAdapter


_LOCALAI_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "documents.search",
        "description": "Search project documents.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}


def _build_provider() -> LLMProviderSettings:
    return LLMProviderSettings(
        name="local_provider",
        type="openai_compatible",
        enabled=True,
        base_url="http://localhost:8081/v1",
        endpoint=None,
        api_key=None,
        auth_header=None,
        auth_token=None,
        timeout_seconds=30,
        stream_timeout_seconds=60,
        headers={},
        extra={},
    )


def _build_resolved_request(
    request: LLMRequest | None = None,
    *,
    supports_tool_calling: bool = False,
) -> ResolvedLLMRequest:
    provider = _build_provider()
    profile = LLMProfileSettings(
        name="local_reasoning",
        enabled=True,
        provider="local_provider",
        model="local-model",
        temperature=None,
        top_p=None,
        max_output_tokens=256,
        max_input_tokens=None,
        max_total_tokens=None,
        timeout_seconds=None,
        stream_timeout_seconds=None,
        supports_streaming=True,
        supports_json_schema=False,
        supports_tool_calling=supports_tool_calling,
        allowed_for=LLMProfileAllowlistSettings(
            usecases=("default_chat",),
            agents=("support_agent",),
            strategies=("direct_agent",),
        ),
        fallback_profiles=(),
        extra={},
    )
    if request is None:
        request = LLMRequest(
            component="agent.support_agent",
            messages=[LLMMessage(role="user", content="Stream the answer")],
            stream=True,
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
        response_format=None,
        max_output_tokens=256,
        agent_name="support_agent",
        strategy_name="direct_agent",
        usecase_name="default_chat",
    )


@pytest.mark.asyncio
async def test_openai_compatible_stream_normalizes_sse_chunks() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"world"}}],"usage":{"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(_build_provider(), client=client)

    events = [event async for event in adapter.stream(_build_resolved_request())]

    await client.aclose()

    assert [event.type for event in events] == ["started", "delta", "delta", "completed"]
    assert events[1].text == "hello "
    assert events[2].text == "world"
    assert events[3].finish_reason == "completed"
    assert events[3].usage is not None
    assert events[3].usage.total_tokens == 10

@pytest.mark.asyncio
async def test_openai_compatible_stream_tool_call_deltas() -> None:
    body = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_docs_1","type":"function","function":{"name":"documents.search","arguments":"{\\"query\\":\\"gateway"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":" path\\"}"}}]}}],"usage":{"prompt_tokens":8,"completion_tokens":4,"total_tokens":12}}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(_build_provider(), client=client)
    request = LLMRequest(
        component="agent.support_agent",
        messages=[LLMMessage(role="user", content="Find the gateway docs")],
        tools=[_LOCALAI_SEARCH_TOOL],
        tool_choice="auto",
        stream=True,
    )

    events = [event async for event in adapter.stream(_build_resolved_request(request, supports_tool_calling=True))]

    await client.aclose()

    assert events[-1].finish_reason == "tool_calls"
    assert events[-1].usage is not None
    assert events[-1].usage.total_tokens == 12
    assert len(events[-1].tool_calls) == 1
    assert events[-1].tool_calls[0].function.arguments == '{"query":"gateway path"}'