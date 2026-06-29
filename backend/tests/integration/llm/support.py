from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.config.loader import YamlConfigurationLoader
from app.config.view import get_llm_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext, RequestContext
from app.llm.factory import LLMRuntimeBundle, _build_provider_adapter
from app.llm.gateway import DefaultLLMGateway
from app.llm.profile_resolver import LLMProfileResolver
from app.llm.provider_base import LLMProviderAdapter
from app.llm.provider_registry import ProviderRegistry
from app.observability.metrics import InMemoryMetricsRecorder
from app.orchestration.core import DirectAgentOrchestrationRuntime
from app.policy.factory import build_policy_runtime
from app.testing.fakes import (
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"
BASE_CONFIG_PATH = FIXTURES_DIR / "valid_minimal.yaml"


async def load_config_view(
    override_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> ConfigurationView:
    loader = YamlConfigurationLoader(
        BASE_CONFIG_PATH,
        override_path=FIXTURES_DIR / override_name,
        env=dict(env or {}),
    )
    return await loader.load()


def build_runtime_bundle(
    config: ConfigurationView,
    *,
    provider_overrides: Mapping[str, LLMProviderAdapter] | None = None,
) -> LLMRuntimeBundle:
    settings = get_llm_settings(config)
    registry = ProviderRegistry(settings.providers)
    overrides = dict(provider_overrides or {})
    for provider_name, provider in settings.providers.items():
        registry.register(
            provider_name,
            overrides.get(provider_name, _build_provider_adapter(provider)),
        )

    policy_service = build_policy_runtime(config).service
    profile_resolver = LLMProfileResolver()
    gateway = DefaultLLMGateway(
        config=config,
        registry=registry,
        profile_resolver=profile_resolver,
        policy_service=policy_service,
        metrics=InMemoryMetricsRecorder(),
    )
    return LLMRuntimeBundle(
        registry=registry,
        policy_service=policy_service,
        profile_resolver=profile_resolver,
        gateway=gateway,
    )


def build_context(
    config: ConfigurationView,
    *,
    trace_store: FakeTraceStore | None = None,
    runtime_metadata: Mapping[str, object] | None = None,
    message: str = "hello integration",
    usecase: str = "default_chat",
    session_id: str = "session_integration_1",
    trace_id: str = "trace_integration_1",
) -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id=session_id,
            message=message,
            usecase=usecase,
            trace_id=trace_id,
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=trace_store or FakeTraceStore(),
        policy=build_policy_runtime(config).service,
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "direct_agent",
            "usecase_name": usecase,
            **dict(runtime_metadata or {}),
        },
    )


def build_orchestrator(
    config: ConfigurationView,
    *,
    trace_store: FakeTraceStore | None = None,
) -> tuple[LLMRuntimeBundle, DirectAgentOrchestrationRuntime]:
    runtime = build_runtime_bundle(config)
    orchestrator = DirectAgentOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=runtime.gateway,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store or FakeTraceStore(),
        policy_service=runtime.policy_service,
        tools=FakeToolGateway(),
    )
    return runtime, orchestrator