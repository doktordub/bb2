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