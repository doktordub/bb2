from __future__ import annotations

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.profile_resolver import LLMProfileResolver
from app.policy.llm_policy import build_llm_policy_request
from tests.unit.llm.support import base_config, build_context


def test_build_llm_policy_request_uses_typed_actor_scope_and_evaluation() -> None:
    config = base_config()
    context = build_context(config)
    resolved = LLMProfileResolver().resolve(
        request=LLMRequest(
            profile="primary_profile",
            messages=[LLMMessage(role="user", content="hello world")],
        ),
        context=context,
    )

    policy_request = build_llm_policy_request(
        action="llm.complete",
        resolved=resolved,
        context=context,
        fallback_from_profile="fallback_profile",
    )

    assert policy_request.actor is not None
    assert policy_request.actor.user_id == "user_1"
    assert policy_request.evaluation is not None
    assert policy_request.evaluation.llm_profile == "primary_profile"
    assert policy_request.evaluation.metadata["fallback_from_profile"] == "fallback_profile"
    assert policy_request.scope["agent_name"] == "support_agent"
    assert policy_request.scope["strategy_name"] == "direct_agent"