from __future__ import annotations

from app.contracts.context import RequestContext
from app.contracts.state import default_workflow_state
from app.orchestration.core import DirectAgentOrchestrationRuntime
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from app.tools.factory import build_tooling_runtime, initialize_tooling_runtime
from app.tools.mcp import FakeMCPClientAdapter


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                        "tools_enabled": True,
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "policy_profile": "default",
                        "tools": {
                            "enabled": True,
                            "allowed_tools": ["documents.search"],
                        },
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["documents.search"],
                }
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
                    "max_retries": 1,
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
                            "tags": ["documents", "search"],
                            "safety_level": "read_only",
                        }
                    },
                },
            },
            "mcp": {
                "main": {
                    "name": "fake_main",
                    "enabled": True,
                    "endpoint": "http://tooling.invalid/mcp",
                    "transport": "http",
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 90,
                    "auth": {"mode": "none"},
                    "tool_discovery_enabled": True,
                }
            },
        }
    )


async def test_direct_runtime_executes_tool_calls_through_real_gateway() -> None:
    config = build_config()
    tooling_runtime = build_tooling_runtime(config)
    await initialize_tooling_runtime(tooling_runtime)

    assert isinstance(tooling_runtime.mcp_adapter, FakeMCPClientAdapter)

    runtime = DirectAgentOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="llm should not run"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=DefaultPolicyService(config),
        tools=tooling_runtime.gateway,
    )

    result = await runtime.run(
        request=RequestContext(
            user_id="user_1",
            session_id="session_tooling_1",
            message="tool: backend architecture",
            usecase="default_chat",
            trace_id="trace_tooling_1",
        ),
        state=default_workflow_state("session_tooling_1"),
    )

    assert result.answer == "Prepared 1 tool intent."
    assert result.agent_name == "support_agent"
    assert result.strategy_name == "direct_agent"
    assert result.tool_calls[0]["tool_name"] == "documents.search"
    assert result.tool_calls[0]["status"] == "planned"
    assert tooling_runtime.mcp_adapter.call_requests == []