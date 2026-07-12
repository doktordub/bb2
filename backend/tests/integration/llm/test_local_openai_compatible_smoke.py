from __future__ import annotations

import os

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LOCAL_LLM_SMOKE") != "1" or not os.getenv("LOCAL_LLM_BASE_URL"),
    reason=(
        "Set RUN_LOCAL_LLM_SMOKE=1 and LOCAL_LLM_BASE_URL to enable the local "
        "OpenAI-compatible smoke test."
    ),
)

tool_smoke = pytest.mark.skipif(
    os.getenv("RUN_LOCAL_LLM_TOOL_SMOKE") != "1",
    reason="Set RUN_LOCAL_LLM_TOOL_SMOKE=1 to enable the native tool-calling smoke test.",
)


@pytest.mark.asyncio
async def test_local_openai_compatible_smoke() -> None:
    config = await load_config_view(
        "llm_openai_compatible_local.yaml",
        env=os.environ,
    )
    runtime = build_runtime_bundle(config)
    context = build_context(config, message="Reply with the single word pong.")

    response = await runtime.gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="Reply with the single word pong.")],
        ),
        context,
    )

    assert response.provider == "local_provider"
    assert response.profile == "local_reasoning"
    assert response.text.strip() != ""


@pytest.mark.asyncio
@tool_smoke
async def test_local_openai_compatible_native_tool_call_smoke() -> None:
    config = await load_config_view(
        "llm_openai_compatible_local.yaml",
        env=os.environ,
    )
    runtime = build_runtime_bundle(config)
    prompt = (
        "You must call the provided diagnostics.echo tool exactly once. "
        "Do not answer directly before the tool result is available."
    )
    context = build_context(config, message=prompt)

    initial = await runtime.gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "diagnostics.echo",
                        "description": "Return the caller-provided text exactly.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                            },
                            "required": ["text"],
                        },
                    },
                }
            ],
            tool_choice="auto",
        ),
        context,
    )

    assert initial.provider == "local_provider"
    assert initial.profile == "local_reasoning"
    assert initial.finish_reason == "tool_calls"
    assert len(initial.tool_calls) == 1
    assert initial.tool_calls[0].function.name == "diagnostics.echo"

    follow_up = await runtime.gateway.complete(
        LLMRequest(
            messages=[
                LLMMessage(role="user", content=prompt),
                LLMMessage(role="assistant", content="", tool_calls=initial.tool_calls),
                LLMMessage(
                    role="tool",
                    content='{"text": "pong"}',
                    tool_call_id=initial.tool_calls[0].id,
                ),
            ],
        ),
        context,
    )

    assert follow_up.provider == "local_provider"
    assert follow_up.profile == "local_reasoning"
    assert follow_up.text.strip() != ""