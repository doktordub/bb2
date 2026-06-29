from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view


@pytest.mark.asyncio
async def test_gateway_stream_runs_through_fake_provider_fixture() -> None:
    config = await load_config_view("llm_fake_streaming.yaml")
    runtime = build_runtime_bundle(config)
    context = build_context(config)

    events = [
        event
        async for event in runtime.gateway.stream(
            LLMRequest(
                messages=[LLMMessage(role="user", content="stream integration")],
                stream=True,
            ),
            context,
        )
    ]

    assert [event.type for event in events] == ["started", "delta", "completed"]
    assert events[0].profile == "fake_streaming"
    assert events[1].text == "fake response"
    assert events[2].finish_reason == "completed"