from __future__ import annotations

import pytest

from app.contracts.health import HEALTH_DEGRADED, HEALTH_OK, ComponentHealth
from app.observability.health import HealthAggregator, HealthCheckResult
from app.observability.redaction import REDACTED_VALUE, Redactor


@pytest.mark.asyncio
async def test_health_aggregator_reports_ok_and_redacts_details() -> None:
    aggregator = HealthAggregator(redactor=Redactor(redact_secrets=True, max_chars=32))
    aggregator.register(
        "trace",
        lambda: HealthCheckResult(
            status=HEALTH_OK,
            details={"provider": "sqlite", "api_key": "super-secret"},
        ),
    )

    payload = await aggregator.evaluate()

    assert payload == {
        "status": "ok",
        "checks": {
            "trace": {
                "status": "ok",
                "provider": "sqlite",
                "api_key": REDACTED_VALUE,
            }
        },
    }


@pytest.mark.asyncio
async def test_health_aggregator_merges_degraded_status() -> None:
    aggregator = HealthAggregator(redactor=Redactor(redact_secrets=True, max_chars=32))
    aggregator.register(
        "memory",
        lambda: ComponentHealth(name="memory", status=HEALTH_DEGRADED, configured=True),
    )

    payload = await aggregator.evaluate()

    assert payload["status"] == "degraded"
    assert payload["checks"]["memory"] == {
        "status": "degraded",
        "configured": True,
    }


@pytest.mark.asyncio
async def test_health_aggregator_converts_check_failure_to_failed_component() -> None:
    aggregator = HealthAggregator(redactor=Redactor(redact_secrets=True, max_chars=32))

    def broken_check() -> HealthCheckResult:
        raise RuntimeError("boom")

    aggregator.register("trace", broken_check)
    payload = await aggregator.evaluate(include_details=False)

    assert payload == {
        "status": "failed",
        "checks": {
            "trace": {
                "status": "failed",
            }
        },
    }