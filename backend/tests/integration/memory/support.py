from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.config.loader import YamlConfigurationLoader
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext, RequestContext
from app.memory.factory import build_memory_gateway
from app.testing.fakes import (
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
CONFIG_FIXTURES_DIR = FIXTURES_DIR / "config"
BASE_CONFIG_PATH = CONFIG_FIXTURES_DIR / "valid_minimal.yaml"


async def load_config_view(
    override_name: str,
    *,
    base_name: str = "valid_minimal.yaml",
    env: Mapping[str, str] | None = None,
) -> ConfigurationView:
    loader = YamlConfigurationLoader(
        CONFIG_FIXTURES_DIR / base_name,
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env=dict(env or {}),
    )
    return await loader.load()


async def build_gateway(config: ConfigurationView):
    persistence = config.persistence_settings()
    return await build_memory_gateway(config, persistence.memory)


def build_context(
    config: ConfigurationView,
    *,
    trace_store: FakeTraceStore | None = None,
    runtime_metadata: Mapping[str, object] | None = None,
    message: str = "memory integration",
    usecase: str = "default_chat",
    session_id: str = "session_memory_integration_1",
    trace_id: str = "trace_memory_integration_1",
) -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user-1",
            session_id=session_id,
            message=message,
            usecase=usecase,
            trace_id=trace_id,
            metadata={"project_id": "project-1"},
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=trace_store or FakeTraceStore(),
        policy=FakePolicyService(),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "direct_agent",
            "usecase_name": usecase,
            **dict(runtime_metadata or {}),
        },
    )