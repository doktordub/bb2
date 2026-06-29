from __future__ import annotations

from typing import Any

import pytest

from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.tools.errors import ToolArgumentValidationError, ToolPolicyDeniedError, ToolTimeoutError
from app.tools.models import ResolvedToolDefinition
from app.tools.retry import is_retryable_error, retry_attempts_for_request


async def test_gateway_denies_unknown_tool_before_adapter_call(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    gateway, context, _trace_store, adapter, _runtime, _config = tooling_env_factory(
        tooling_values
    )

    with pytest.raises(ToolPolicyDeniedError, match="Unknown logical tool"):
        await gateway.execute(
            ToolExecutionRequest(
                tool_name="missing.tool",
                arguments={"query": "nope"},
                scopes=ToolScopes(project_id="proj-1"),
            ),
            context,
        )

    assert getattr(adapter, "call_requests", []) == []


async def test_gateway_denies_allowlist_mismatch_before_adapter_call(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    gateway, context, _trace_store, adapter, _runtime, _config = tooling_env_factory(
        tooling_values,
        usecase="admin_only",
    )

    with pytest.raises(ToolPolicyDeniedError, match="active use case"):
        await gateway.execute(
            ToolExecutionRequest(
                tool_name="documents.search",
                arguments={"query": "policy"},
                scopes=ToolScopes(project_id="proj-1"),
            ),
            context,
        )

    assert getattr(adapter, "call_requests", []) == []


async def test_gateway_denies_destructive_and_approval_required_tools(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    tooling_values["tooling"]["registry"]["tools"]["admin.reset_cache"] = {
        "enabled": True,
        "mcp_tool_name": "admin.reset_cache",
        "description": "Reset remote caches.",
        "allowed_for": {
            "usecases": ["default_chat"],
            "agents": ["support_agent"],
            "strategies": ["direct_agent"],
        },
        "approval_required": False,
        "input_schema_override": {"type": "object"},
        "output_schema_override": {"type": "object"},
        "tags": ["admin"],
        "safety_level": "destructive",
        "extra": {},
    }
    tooling_values["tooling"]["registry"]["tools"]["billing.charge"] = {
        "enabled": True,
        "mcp_tool_name": "billing.charge",
        "description": "Charge a customer.",
        "allowed_for": {
            "usecases": ["default_chat"],
            "agents": ["support_agent"],
            "strategies": ["direct_agent"],
        },
        "approval_required": True,
        "input_schema_override": {
            "type": "object",
            "properties": {"amount": {"type": "number", "minimum": 0}},
            "required": ["amount"],
            "additionalProperties": False,
        },
        "output_schema_override": {"type": "object"},
        "tags": ["billing"],
        "safety_level": "write",
        "extra": {},
    }
    gateway, context, _trace_store, adapter, _runtime, _config = tooling_env_factory(
        tooling_values
    )

    with pytest.raises(ToolPolicyDeniedError, match="destructive"):
        await gateway.execute(
            ToolExecutionRequest(
                tool_name="admin.reset_cache",
                arguments={},
                scopes=ToolScopes(project_id="proj-1"),
            ),
            context,
        )

    with pytest.raises(ToolPolicyDeniedError, match="requires approval"):
        await gateway.execute(
            ToolExecutionRequest(
                tool_name="billing.charge",
                arguments={"amount": 12},
                scopes=ToolScopes(project_id="proj-1"),
            ),
            context,
        )

    assert getattr(adapter, "call_requests", []) == []


def test_retry_helpers_apply_safe_retry_rules() -> None:
    read_only = ResolvedToolDefinition(
        logical_name="documents.search",
        mcp_tool_name="documents.search",
        safety_level="read_only",
    )
    write_tool = ResolvedToolDefinition(
        logical_name="notes.write",
        mcp_tool_name="notes.write",
        safety_level="write",
    )
    destructive_tool = ResolvedToolDefinition(
        logical_name="admin.reset_cache",
        mcp_tool_name="admin.reset_cache",
        safety_level="destructive",
    )

    assert retry_attempts_for_request(
        definition=read_only,
        default_max_retries=2,
        idempotency_key=None,
    ) == 3
    assert retry_attempts_for_request(
        definition=write_tool,
        default_max_retries=2,
        idempotency_key=None,
    ) == 1
    assert retry_attempts_for_request(
        definition=write_tool,
        default_max_retries=2,
        idempotency_key="idem-1",
    ) == 3
    assert retry_attempts_for_request(
        definition=destructive_tool,
        default_max_retries=2,
        idempotency_key="idem-1",
    ) == 1
    assert is_retryable_error(
        ToolTimeoutError("timed out"),
        definition=read_only,
        idempotency_key=None,
    ) is True
    assert is_retryable_error(
        ToolArgumentValidationError("bad args"),
        definition=read_only,
        idempotency_key=None,
    ) is False