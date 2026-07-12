from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.settings import PolicyProfileSettings, PolicyVisualizationSettings
from app.policy.visualization_policy import (
    build_visualization_policy_request,
    evaluate_visualization_request,
)
from app.testing.fakes import FakeConfigurationView
from app.visualization.models import VisualizationContext


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="build a chart",
                usecase="support_chat",
                trace_id="trace-1",
            ),
            runtime_metadata={"strategy_name": "direct_agent", "agent_name": "chart_agent"},
            config=FakeConfigurationView({}),
        ),
    )


def _build_visualization_context() -> VisualizationContext:
    return VisualizationContext(
        user_id="user-1",
        session_id="session-1",
        usecase="support_chat",
        agent_name="chart_agent",
        trace_id="trace-1",
        policy_scope={"tenant_id": "tenant-1", "project_id": "project-1"},
        config={},
    )


def test_build_visualization_policy_request_preserves_scope_and_metadata() -> None:
    request = build_visualization_policy_request(
        action="visualization.build",
        component="app.visualization.gateway",
        visualization_context=_build_visualization_context(),
        metadata={"chart_type": "bar", "row_count": 3},
    )

    assert request.scope["session_id"] == "session-1"
    assert request.scope["agent_name"] == "chart_agent"
    assert request.scope["tenant_id"] == "tenant-1"
    assert request.metadata["chart_type"] == "bar"
    assert request.evaluation is not None
    assert request.evaluation.tags == ("visualization", "visualization.build")


@pytest.mark.asyncio
async def test_visualization_policy_denies_when_feature_disabled() -> None:
    decision = await evaluate_visualization_request(
        build_visualization_policy_request(
            action="visualization.build",
            component="app.visualization.gateway",
            visualization_context=_build_visualization_context(),
            metadata={
                "stage": "pre_build",
                "chart_type": "bar",
                "renderer": "echarts",
                "data_source": "workflow_state",
                "row_count": 3,
                "field_names": ["month", "revenue"],
            },
        ),
        _build_context(),
        PolicyProfileSettings(name="default"),
        FakeConfigurationView({}),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.visualization.disabled"


@pytest.mark.asyncio
async def test_visualization_policy_denies_tool_data_when_not_allowed() -> None:
    decision = await evaluate_visualization_request(
        build_visualization_policy_request(
            action="visualization.build",
            component="app.visualization.gateway",
            visualization_context=_build_visualization_context(),
            metadata={
                "stage": "pre_build",
                "chart_type": "bar",
                "renderer": "echarts",
                "data_source": "tool",
                "row_count": 3,
                "field_names": ["month", "revenue"],
            },
        ),
        _build_context(),
        PolicyProfileSettings(
            name="default",
            visualization=PolicyVisualizationSettings(enabled=True),
        ),
        FakeConfigurationView({}),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.visualization.tool_denied"


@pytest.mark.asyncio
async def test_visualization_policy_allows_supported_build_requests() -> None:
    decision = await evaluate_visualization_request(
        build_visualization_policy_request(
            action="visualization.build",
            component="app.visualization.gateway",
            visualization_context=_build_visualization_context(),
            metadata={
                "stage": "post_summary",
                "chart_type": "line",
                "renderer": "echarts",
                "data_source": "workflow_state",
                "data_mode": "inline",
                "row_count": 12,
                "series_count": 1,
                "category_count": 12,
                "field_names": ["month", "revenue"],
                "summary_token_estimate": 120,
            },
        ),
        _build_context(),
        PolicyProfileSettings(
            name="default",
            visualization=PolicyVisualizationSettings(
                enabled=True,
                max_rows_inline=100,
                max_rows_artifact_store=200,
                max_series=4,
                max_categories=20,
                max_context_summary_tokens=200,
            ),
        ),
        FakeConfigurationView({}),
    )

    assert decision is not None
    assert decision.decision == "allow"
    assert decision.reason_code == "policy.visualization.allowed"