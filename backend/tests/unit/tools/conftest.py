from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from app.tools.factory import ToolingRuntimeBundle, build_tooling_runtime
from app.tools.gateway import DefaultToolGateway
from app.tools.mcp import FakeMCPClientAdapter
from app.tools.mcp.protocol_models import MCPClientAdapter


def _base_tooling_values() -> dict[str, Any]:
    return {
        "usecases": {
            "default_chat": {"policy_profile": "default"},
            "admin_only": {"policy_profile": "default"},
        },
        "policy": {
            "default_profile": "default",
            "profiles": {
                "default": {
                    "deny_unknown_tools": True,
                    "deny_unknown_llm_profiles": True,
                    "require_memory_scope": True,
                    "allow_memory_writes": False,
                }
            },
        },
        "tooling": {
            "enabled": True,
            "defaults": {
                "timeout_seconds": 45,
                "stream_timeout_seconds": 90,
                "max_retries": 2,
                "max_argument_bytes": 4096,
                "max_result_bytes": 65536,
                "trace_arguments": False,
                "trace_results": False,
                "discovery_on_startup": True,
                "discovery_refresh_seconds": 120,
            },
            "registry": {
                "allow_discovered_tools": True,
                "require_configured_allowlist": True,
                "tools": {
                    "documents.search": {
                        "enabled": True,
                        "mcp_tool_name": "documents.search",
                        "description": "Search indexed documents.",
                        "allowed_for": {
                            "usecases": ["default_chat"],
                            "agents": ["support_agent"],
                            "strategies": ["direct_agent"],
                        },
                        "timeout_seconds": 30,
                        "max_argument_bytes": 2048,
                        "max_result_bytes": 16384,
                        "approval_required": False,
                        "input_schema_override": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "minLength": 1},
                                "limit": {"type": "integer", "minimum": 1},
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                        "output_schema_override": {"type": "object"},
                        "tags": ["documents", "search"],
                        "safety_level": "read_only",
                        "extra": {"supports_streaming": True},
                    },
                    "notes.write": {
                        "enabled": True,
                        "mcp_tool_name": "notes.write",
                        "description": "Write a support note.",
                        "allowed_for": {
                            "usecases": ["default_chat"],
                            "agents": ["support_agent"],
                            "strategies": ["direct_agent"],
                        },
                        "timeout_seconds": 30,
                        "max_argument_bytes": 2048,
                        "max_result_bytes": 16384,
                        "approval_required": False,
                        "input_schema_override": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "minLength": 1}
                            },
                            "required": ["text"],
                            "additionalProperties": False,
                        },
                        "output_schema_override": {"type": "object"},
                        "tags": ["notes", "write"],
                        "safety_level": "write",
                        "extra": {},
                    },
                    "ops.hidden": {
                        "enabled": True,
                        "mcp_tool_name": "ops.hidden",
                        "description": "Hidden operations tool.",
                        "allowed_for": {
                            "usecases": ["admin_only"],
                            "agents": ["support_agent"],
                            "strategies": ["direct_agent"],
                        },
                        "timeout_seconds": 30,
                        "max_argument_bytes": 2048,
                        "max_result_bytes": 16384,
                        "approval_required": False,
                        "input_schema_override": {"type": "object"},
                        "output_schema_override": {"type": "object"},
                        "tags": ["ops"],
                        "safety_level": "read_only",
                        "extra": {},
                    },
                },
            },
        },
        "mcp": {
            "main": {
                "name": "fake_main",
                "enabled": True,
                "endpoint": "http://localhost:9001/mcp",
                "transport": "sse",
                "timeout_seconds": 45,
                "stream_timeout_seconds": 90,
                "auth": {"mode": "none"},
                "tool_discovery_enabled": True,
            }
        },
    }


@pytest.fixture
def tooling_values() -> dict[str, Any]:
    return deepcopy(_base_tooling_values())


@pytest.fixture
def tooling_env_factory():
    def factory(
        values: dict[str, Any] | None = None,
        *,
        adapter: MCPClientAdapter | None = None,
        usecase: str = "default_chat",
        agent_name: str = "support_agent",
        strategy_name: str = "direct_agent",
    ) -> tuple[
        DefaultToolGateway,
        OrchestrationContext,
        FakeTraceStore,
        MCPClientAdapter,
        ToolingRuntimeBundle,
        FakeConfigurationView,
    ]:
        config = FakeConfigurationView(deepcopy(values or _base_tooling_values()))
        selected_adapter = adapter
        if selected_adapter is None:
            seed_runtime = build_tooling_runtime(
                config,
                mcp_adapter=FakeMCPClientAdapter(),
            )
            selected_adapter = FakeMCPClientAdapter.from_registry_entries(
                registry_entries=seed_runtime.registry_entries,
                enabled=seed_runtime.settings.enabled and seed_runtime.settings.mcp_server.enabled,
                endpoint=seed_runtime.settings.mcp_server.endpoint,
                auth_mode=seed_runtime.settings.mcp_server.auth.mode,
                metadata={"server_name": seed_runtime.settings.mcp_server.name},
            )

        runtime = build_tooling_runtime(config, mcp_adapter=selected_adapter)
        gateway = DefaultToolGateway(
            settings=runtime.settings,
            registry=runtime.registry,
            argument_validator=runtime.argument_validator,
            result_normalizer=runtime.result_normalizer,
            mcp_adapter=runtime.mcp_adapter,
        )
        trace_store = FakeTraceStore()
        context = OrchestrationContext(
            request=RequestContext(
                user_id="user_1",
                session_id="session_1",
                message="hello",
                usecase=usecase,
                trace_id="trace_tool_1",
            ),
            llm=FakeLLMGateway(),
            memory=FakeMemoryGateway(),
            state=FakeWorkflowStateStore(),
            tools=gateway,
            trace=trace_store,
            policy=DefaultPolicyService(config),
            config=config,
            runtime_metadata={
                "agent_name": agent_name,
                "strategy_name": strategy_name,
            },
        )
        return gateway, context, trace_store, runtime.mcp_adapter, runtime, config

    return factory