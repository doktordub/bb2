"""Policy helpers for structured agent execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agents.capabilities import require_capability
from app.agents.errors import AgentInputValidationError, AgentPolicyDeniedError
from app.agents.models import AgentCapabilities, AgentRunRequest
from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyDeniedError
from app.contracts.policy import PolicyAction, PolicyRequest
from app.orchestration.models import sanitize_metadata


def build_policy_scope(
    request: AgentRunRequest,
    *,
    agent_name: str,
) -> dict[str, Any]:
    """Build a safe scope block for agent-related policy checks."""

    return {
        "session_id": request.session_id,
        "trace_id": request.trace_id,
        "usecase": request.usecase,
        "project_id": request.project_id,
        "agent_name": agent_name,
        "strategy_name": request.strategy_name,
    }


async def require_policy_action(
    context: OrchestrationContext,
    *,
    request: AgentRunRequest,
    action: PolicyAction,
    component: str,
    agent_name: str,
    resource: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Run an agent-scoped policy check and remap denials into agent errors."""

    try:
        await context.policy.require_allowed(
            PolicyRequest(
                action=action,
                component=component,
                resource=resource or agent_name,
                scope=build_policy_scope(request, agent_name=agent_name),
                metadata=sanitize_metadata(metadata),
            ),
            context,
        )
    except PolicyDeniedError as exc:
        raise AgentPolicyDeniedError(str(exc), metadata=metadata) from exc


def require_capability_allowed(
    capabilities: AgentCapabilities,
    capability_name: str,
    *,
    agent_name: str,
) -> None:
    """Validate one capability before a structured execution path uses it."""

    require_capability(capabilities, capability_name, agent_name=agent_name)


async def require_capability_policy(
    context: OrchestrationContext,
    *,
    request: AgentRunRequest,
    capability_name: str,
    component: str,
    agent_name: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Run a typed policy check for one agent capability use."""

    try:
        await context.policy.require_allowed(
            PolicyRequest(
                action="agent.invoke",
                component=component,
                resource=agent_name,
                scope=build_policy_scope(request, agent_name=agent_name),
                metadata=sanitize_metadata(
                    {
                        "agent_action": "use_capability",
                        "agent_capability": capability_name,
                        **({} if metadata is None else dict(metadata)),
                    }
                ),
            ),
            context,
        )
    except PolicyDeniedError as exc:
        raise AgentPolicyDeniedError(str(exc), metadata=metadata) from exc


def require_project_scope(
    request: AgentRunRequest,
    *,
    agent_name: str,
) -> None:
    """Require an active project scope for project-scoped agent work."""

    if request.project_id is None:
        raise AgentInputValidationError(
            f"Agent '{agent_name}' requires an active project scope."
        )


__all__ = [
    "build_policy_scope",
    "require_capability_allowed",
    "require_capability_policy",
    "require_project_scope",
    "require_policy_action",
]