from __future__ import annotations

import pytest

from app.contracts.errors import PolicyApprovalRequiredError
from app.contracts.policy import PolicyDecision
from app.policy.approval_policy import build_approval_required_decision, raise_for_approval_required


def test_build_approval_required_decision_adds_obligation() -> None:
    decision = build_approval_required_decision(
        reason="Approval required",
        reason_code="policy.tool.approval_required",
        target="tool.execute",
        metadata={"resource": "billing.charge"},
        value="write",
    )

    assert decision.decision == "approval_required"
    assert decision.obligations[0].kind == "require_approval"


def test_raise_for_approval_required_raises_distinct_error() -> None:
    with pytest.raises(PolicyApprovalRequiredError, match="Approval required"):
        raise_for_approval_required(
            PolicyDecision.approval_required(reason="Approval required")
        )