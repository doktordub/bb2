"""Session-domain policy evaluators used by the internal policy engine."""

from __future__ import annotations

from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyAction, PolicyDecision, PolicyRequest
from app.policy.settings import PolicyProfileSettings


async def evaluate_session_access(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
    config: ConfigurationView,
) -> PolicyDecision | None:
    """Evaluate explicit session reset and history access requests."""

    _ = profile
    _ = config
    if request.action not in {"session.reset", "session.read_history"}:
        return None

    session_id = request.resource or _read_optional_str(request.scope.get("session_id"))
    actor = request.resolved_actor()
    owner_user_id = _read_optional_str(request.metadata.get("owner_user_id"))
    owner_user_id_hash = _read_optional_str(request.metadata.get("owner_user_id_hash"))

    if session_id is None:
        return PolicyDecision.deny(
            reason="The session identifier is required.",
            reason_code="policy.session.missing_session_id",
        )

    if actor.actor_type == "anonymous":
        return PolicyDecision.deny(
            reason="Anonymous session access is not allowed.",
            reason_code="policy.session.anonymous_denied",
            metadata={"resource": session_id},
        )

    if owner_user_id is not None and actor.user_id is not None and owner_user_id != actor.user_id:
        return PolicyDecision.deny(
            reason="The requested session is owned by another user.",
            reason_code="policy.session.owner_mismatch",
            metadata={"resource": session_id},
        )

    actor_hash = _read_optional_str(actor.attributes.get("user_id_hash"))
    if owner_user_id_hash is not None and actor_hash is not None and owner_user_id_hash != actor_hash:
        return PolicyDecision.deny(
            reason="The requested session is not accessible to this actor.",
            reason_code="policy.session.owner_hash_mismatch",
            metadata={"resource": session_id},
        )

    reason_code = (
        "policy.session.reset_allowed"
        if request.action == "session.reset"
        else "policy.session.history_allowed"
    )
    return PolicyDecision.allow(
        reason_code=reason_code,
        metadata={"resource": session_id},
    )


def build_session_policy_request(
    *,
    action: PolicyAction,
    component: str,
    session_id: str,
    user_id: str,
    user_id_hash: str | None,
    usecase_name: str | None,
    owner_user_id: str | None = None,
    owner_user_id_hash: str | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> PolicyRequest:
    """Build a normalized policy request for session-domain operations."""

    metadata: dict[str, object] = {
        "actor_type": "user",
        "actor_id": user_id,
    }
    if user_id_hash is not None:
        metadata["actor_attributes"] = {"user_id_hash": user_id_hash}
    if owner_user_id is not None:
        metadata["owner_user_id"] = owner_user_id
    if owner_user_id_hash is not None:
        metadata["owner_user_id_hash"] = owner_user_id_hash
    if extra_metadata:
        metadata.update(extra_metadata)

    return PolicyRequest(
        action=action,
        component=component,
        resource=session_id,
        scope={
            "session_id": session_id,
            "usecase_name": usecase_name,
            "user_id": user_id,
        },
        metadata=metadata,
    )


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None