from __future__ import annotations

from typing import cast

import pytest

from app.contracts.context import RequestContext
from app.contracts.state import default_workflow_state
from app.llm.providers import FakeLLMProviderAdapter
from tests.integration.llm.support import build_orchestrator, load_config_view


@pytest.mark.asyncio
async def test_orchestration_runtime_uses_the_configured_llm_profile() -> None:
    config = await load_config_view("llm_fake_basic.yaml")
    runtime, orchestrator = build_orchestrator(config)

    result = await orchestrator.run(
        request=RequestContext(
            user_id="user_1",
            session_id="session_orchestration_1",
            message="route this through the configured llm profile",
            usecase="default_chat",
            trace_id="trace_orchestration_1",
        ),
        state=default_workflow_state("session_orchestration_1"),
    )

    provider = cast(FakeLLMProviderAdapter, runtime.registry.get("fake_provider"))
    assert result.answer == "fake response"
    assert result.llm_profile == "fake_basic"
    assert provider.calls[0].request.profile_name == "fake_basic"