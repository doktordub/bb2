from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.settings import PolicyProfileSettings, PolicyStreamSettings
from app.policy.stream_policy import (
    build_stream_policy_request,
    evaluate_stream_request,
    infer_stream_payload_category,
)
from app.session.models import SessionStreamEvent
from app.testing.fakes import FakeConfigurationView


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="hello",
                usecase="default_chat",
                trace_id="trace-1",
            ),
            runtime_metadata={},
            config=FakeConfigurationView({}),
        ),
    )


def test_stream_payload_category_detects_raw_provider_chunk() -> None:
    event = SessionStreamEvent(
        event_type="response.delta",
        trace_id="trace-1",
        session_id="session-1",
        data={"provider_chunk": "raw"},
    )
    assert infer_stream_payload_category(event) == "raw_provider_chunk"


@pytest.mark.asyncio
async def test_stream_policy_denies_raw_provider_chunks() -> None:
    context = _build_context()
    event = SessionStreamEvent(
        event_type="response.delta",
        trace_id="trace-1",
        session_id="session-1",
        data={"provider_chunk": "raw"},
    )
    request = build_stream_policy_request(event=event, payload_category="raw_provider_chunk")

    decision = await evaluate_stream_request(
        request,
        context,
        PolicyProfileSettings(name="default", stream=PolicyStreamSettings()),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.stream.raw_payload_denied"


@pytest.mark.asyncio
async def test_stream_policy_allows_safe_response_delta() -> None:
    context = _build_context()
    event = SessionStreamEvent(
        event_type="response.delta",
        trace_id="trace-1",
        session_id="session-1",
        data={"text": "hello"},
    )
    request = build_stream_policy_request(event=event, payload_category="safe_summary")

    decision = await evaluate_stream_request(
        request,
        context,
        PolicyProfileSettings(name="default"),
    )

    assert decision is not None
    assert decision.decision == "allow"
    assert decision.reason_code == "policy.stream.allowed"


@pytest.mark.asyncio
async def test_stream_policy_allows_safe_artifact_completed_event() -> None:
    context = _build_context()
    event = SessionStreamEvent(
        event_type="artifact.completed",
        trace_id="trace-1",
        session_id="session-1",
        data={
            "artifact": {
                "artifact_id": "chart-1",
                "type": "chart",
                "chart_type": "bar",
                "title": "Revenue",
                "renderer": "echarts",
                "spec_version": "1.0",
                "data_mode": "inline",
                "data": [{"month": "Jan", "revenue": 1200}],
                "data_ref": None,
                "encoding": {"x": "month", "y": ["revenue"]},
                "options": {},
                "warnings": [],
                "metadata": {},
            }
        },
    )
    request = build_stream_policy_request(event=event, payload_category="safe_summary")

    decision = await evaluate_stream_request(
        request,
        context,
        PolicyProfileSettings(name="default"),
    )

    assert decision is not None
    assert decision.decision == "allow"
    assert decision.reason_code == "policy.stream.allowed"