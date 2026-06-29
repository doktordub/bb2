"""Internal helpers for matching policy rules to requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.policy import PolicyRequest, PolicyScope


class PolicyRuleMatcher:
    """Match internal policy rules to one request."""

    def matches(self, *, actions: tuple[str, ...], component_prefixes: tuple[str, ...], request: PolicyRequest) -> bool:
        if request.action not in actions:
            return False
        if not component_prefixes:
            return True
        return any(request.component.startswith(prefix) for prefix in component_prefixes)


def normalize_name_list(value: object) -> tuple[str, ...] | None:
    """Normalize an optional allowlist into a deduplicated tuple."""

    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        current = item.strip()
        if current and current not in normalized:
            normalized.append(current)
    return tuple(normalized)


def is_name_allowed(raw_values: object, value: str | None) -> bool:
    """Return True when an allowlist is empty or contains the requested value."""

    normalized_values = normalize_name_list(raw_values)
    if normalized_values is None:
        return True
    if not normalized_values:
        return True
    if value is None:
        return False
    return value in normalized_values


def has_memory_scope(scope: PolicyScope | Mapping[str, Any]) -> bool:
    """Return True when at least one meaningful memory scope field is present."""

    if isinstance(scope, PolicyScope):
        values = {
            "user_id": scope.user_id,
            "project_id": scope.project_id,
            "tenant_id": scope.tenant_id,
            "session_id": scope.session_id,
            "usecase_name": scope.usecase_name,
            "memory_scope": scope.memory_scope,
        }
    else:
        values = dict(scope)
    keys = {
        "user_id",
        "project_id",
        "tenant_id",
        "usecase",
        "usecase_name",
        "session_id",
        "memory_scope",
    }
    return any(values.get(key) for key in keys)