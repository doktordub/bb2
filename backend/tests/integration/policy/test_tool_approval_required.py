from __future__ import annotations

from copy import deepcopy

import pytest

from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.tools.errors import ToolPolicyApprovalRequiredError
from tests.unit.tools.conftest import _base_tooling_values, tooling_env_factory


@pytest.mark.asyncio
async def test_tool_gateway_returns_approval_required_before_adapter_call() -> None:
    tooling_values = deepcopy(_base_tooling_values())
    tooling_values["policy"]["profiles"]["default"]["allow_write_tools"] = True
    tooling_values["policy"]["profiles"]["default"]["approval"] = {
        "require_approval_for_write_tools": True,
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
        "approval_required": False,
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
    factory = tooling_env_factory.__wrapped__() if hasattr(tooling_env_factory, "__wrapped__") else tooling_env_factory()  # type: ignore[misc]
    gateway, context, _trace_store, adapter, _runtime, _config = factory(tooling_values)

    with pytest.raises(ToolPolicyApprovalRequiredError, match="requires approval"):
        await gateway.execute(
            ToolExecutionRequest(
                tool_name="billing.charge",
                arguments={"amount": 12},
                scopes=ToolScopes(project_id="proj-1"),
            ),
            context,
        )

    assert getattr(adapter, "call_requests", []) == []