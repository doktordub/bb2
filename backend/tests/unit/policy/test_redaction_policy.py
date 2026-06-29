from __future__ import annotations

from app.contracts.policy import PolicyDecision, PolicyObligation
from app.observability.redaction import Redactor
from app.policy.redaction_policy import apply_redaction_obligations


def test_redaction_policy_applies_redact_obligation() -> None:
    payload = {"token": "secret", "status": "ok"}
    decision = PolicyDecision.allow(
        obligations=(PolicyObligation(kind="redact", target="token"),),
    )

    result = apply_redaction_obligations(payload, decision=decision, redactor=Redactor())

    assert result["token"] == "***REDACTED***"
    assert result["status"] == "ok"


def test_redaction_policy_omits_payload_when_required() -> None:
    payload = {"token": "secret", "status": "ok"}
    decision = PolicyDecision.allow(
        obligations=(PolicyObligation(kind="omit_payload"),),
    )

    result = apply_redaction_obligations(payload, decision=decision, redactor=Redactor())

    assert result == {}