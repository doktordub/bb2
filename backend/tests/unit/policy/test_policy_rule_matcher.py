from __future__ import annotations

from app.contracts.policy import PolicyRequest
from app.policy.rule_matcher import PolicyRuleMatcher, has_memory_scope, is_name_allowed, normalize_name_list


def test_rule_matcher_filters_by_action_and_component_prefix() -> None:
    matcher = PolicyRuleMatcher()
    request = PolicyRequest(
        action="tool.execute",
        component="app.tools.gateway",
        resource="documents.search",
    )

    assert matcher.matches(
        actions=("tool.execute",),
        component_prefixes=("app.tools",),
        request=request,
    )
    assert not matcher.matches(
        actions=("llm.complete",),
        component_prefixes=("app.llm",),
        request=request,
    )
    assert not matcher.matches(
        actions=("tool.execute",),
        component_prefixes=("app.memory",),
        request=request,
    )


def test_allowlist_and_scope_helpers_are_deterministic() -> None:
    assert normalize_name_list([" documents.search ", "documents.search", "notes.write"]) == (
        "documents.search",
        "notes.write",
    )
    assert is_name_allowed((), None)
    assert is_name_allowed(["default_chat"], "default_chat")
    assert not is_name_allowed(["default_chat"], "admin_ops")
    assert has_memory_scope({"project_id": "proj-1"})
    assert not has_memory_scope({"metadata": {"ignored": True}})