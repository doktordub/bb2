"""Policy-aware redaction helpers for exposure boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.policy import PolicyDecision
from app.observability.redaction import REDACTED_VALUE, Redactor


def apply_redaction_obligations(
    payload: Mapping[str, Any] | None,
    *,
    decision: PolicyDecision,
    redactor: Redactor,
) -> dict[str, Any]:
    """Apply policy-driven omission or redaction obligations to a payload."""

    if not payload:
        return {}

    working = dict(payload)
    omit_payload = any(obligation.kind == "omit_payload" for obligation in decision.obligations)
    if omit_payload:
        return {}

    redacted = redactor.redact(working)
    if not isinstance(redacted, dict):
        return {"value": REDACTED_VALUE}

    result = dict(redacted)
    for obligation in decision.obligations:
        if obligation.kind != "redact":
            continue
        target = obligation.target
        if isinstance(target, str) and target in result:
            result[target] = REDACTED_VALUE
    return result