from __future__ import annotations

from typing import Any

from app.config.view import MemorySettings, get_memory_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.memory.adapters.base import MemoryAdapter
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.gateway import DefaultMemoryGateway
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_memory_settings(
    *,
    enabled: bool = True,
    provider: str = "fake",
    default_scope: str = "project",
    max_result_chars: int = 24,
    limit_max: int = 5,
    allow_writes: bool = True,
    enable_export_by_scope: bool = False,
    enable_delete_by_scope: bool = False,
    hard_delete_enabled: bool = False,
    delete_by_scope_requires_confirm: bool = True,
    tombstone_on_forget: bool = True,
) -> MemorySettings:
    config = FakeConfigurationView(
        {
            "memory": {
                "enabled": enabled,
                "provider": provider,
                "required": False,
                "defaults": {
                    "default_scope": default_scope,
                    "top_k": 3,
                    "max_result_chars": max_result_chars,
                },
                "search": {
                    "limit_max": limit_max,
                },
                "lifecycle": {
                    "allow_writes": allow_writes,
                    "require_durable_scope_for_writes": True,
                    "allow_session_scope_only_writes": False,
                    "require_durable_scope_for_delete_export": True,
                },
                "privacy": {
                    "enable_export_by_scope": enable_export_by_scope,
                    "enable_delete_by_scope": enable_delete_by_scope,
                    "hard_delete_enabled": hard_delete_enabled,
                    "delete_by_scope_requires_confirm": delete_by_scope_requires_confirm,
                    "tombstone_on_forget": tombstone_on_forget,
                    "require_policy_approval_for_delete_export": True,
                },
            },
            "features": {"memory_enabled": enabled},
        }
    )
    return get_memory_settings(config)


def build_context(
    *,
    user_id: str = "user-1",
    project_id: str | None = "project-1",
    usecase: str = "support",
    agent_name: str = "assistant_agent",
    config_values: dict[str, Any] | None = None,
    trace_store: FakeTraceStore | None = None,
    policy: FakePolicyService | None = None,
    runtime_metadata: dict[str, object] | None = None,
) -> OrchestrationContext:
    metadata: dict[str, Any] = {}
    if project_id is not None:
        metadata["project_id"] = project_id

    return OrchestrationContext(
        request=RequestContext(
            user_id=user_id,
            session_id="session-1",
            message="hello world",
            usecase=usecase,
            trace_id="trace-1",
            metadata=metadata,
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=trace_store or FakeTraceStore(),
        policy=policy or FakePolicyService(),
        config=FakeConfigurationView(config_values or {}),
        runtime_metadata={
            "agent_name": agent_name,
            "strategy_name": "default_strategy",
            "usecase_name": usecase,
            **dict(runtime_metadata or {}),
        },
    )


def build_project_scope_config(
    *,
    usecase_name: str,
    agent_name: str,
    strategy_name: str = "default_strategy",
    strategy_type: str = "retrieval_augmented",
    usecase_allowed_project_ids: tuple[str, ...] = (),
    usecase_default_project_id: str | None = None,
    agent_allowed_project_ids: tuple[str, ...] = (),
    agent_default_project_id: str | None = None,
) -> dict[str, Any]:
    return {
        "app": {"active_usecase": usecase_name},
        "orchestration": {
            "defaults": {
                "strategy": strategy_name,
                "fallback_strategy": strategy_name,
            },
            "strategies": {
                strategy_name: {
                    "enabled": True,
                    "type": strategy_type,
                    "default_agent": agent_name,
                }
            },
            "usecases": {
                usecase_name: {
                    "enabled": True,
                    "strategy": strategy_name,
                    "agent": agent_name,
                    "allowed_agents": [agent_name],
                    "policy_profile": "default",
                    "memory": {
                        "enabled": True,
                        "include_document_chunks": True,
                        "default_limit": 8,
                        "allowed_project_ids": list(usecase_allowed_project_ids),
                        "default_project_id": usecase_default_project_id,
                    },
                }
            },
        },
        "agents": {
            "plugins": {
                agent_name: {
                    "enabled": True,
                    "type": "general_assistant",
                    "memory": {
                        "search_enabled": True,
                        "write_enabled": False,
                        "allowed_project_ids": list(agent_allowed_project_ids),
                        "default_project_id": agent_default_project_id,
                    },
                }
            }
        },
    }


def build_gateway(
    *,
    adapter: MemoryAdapter | None = None,
    enabled: bool = True,
    default_scope: str = "project",
    max_result_chars: int = 24,
    limit_max: int = 5,
    allow_writes: bool = True,
    enable_export_by_scope: bool = False,
    enable_delete_by_scope: bool = False,
    hard_delete_enabled: bool = False,
    delete_by_scope_requires_confirm: bool = True,
    tombstone_on_forget: bool = True,
) -> DefaultMemoryGateway:
    return DefaultMemoryGateway(
        settings=build_memory_settings(
            enabled=enabled,
            default_scope=default_scope,
            max_result_chars=max_result_chars,
            limit_max=limit_max,
            allow_writes=allow_writes,
            enable_export_by_scope=enable_export_by_scope,
            enable_delete_by_scope=enable_delete_by_scope,
            hard_delete_enabled=hard_delete_enabled,
            delete_by_scope_requires_confirm=delete_by_scope_requires_confirm,
            tombstone_on_forget=tombstone_on_forget,
        ),
        adapter=adapter or FakeMemoryAdapter(),
    )