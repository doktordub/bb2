"""Deterministic fake chart agent for orchestration and session tests."""

from __future__ import annotations

from app.agents.base import LegacyCompatibleAgent
from app.agents.models import AgentRunRequest, AgentRunResult
from app.agents.result_builder import build_run_result
from app.contracts.context import OrchestrationContext
from app.visualization.chart_summary_builder import build_chart_context_contribution
from app.visualization.models import ChartArtifact, ChartContextSummary


class FakeVisualizationAgent(LegacyCompatibleAgent):
    """Return one stable chart artifact and summary for runtime integration tests."""

    name = "chart_agent"
    type = "chart_agent"
    description = "Deterministic fake chart agent."

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AgentRunResult:
        del context
        artifact = ChartArtifact(
            artifact_id="chart_vis_001",
            chart_type="bar",
            title="Revenue by Month",
            description="Monthly revenue totals.",
            renderer="echarts",
            spec_version="1.0",
            data_mode="inline",
            data=[
                {"month": "Jan", "revenue": 1200},
                {"month": "Feb", "revenue": 1450},
            ],
            data_ref="artifact://session_runtime_chart/chart_vis_001",
            encoding={"x": "month", "y": ["revenue"]},
            metadata={"source": "workflow_state"},
        )
        summary = ChartContextSummary(
            artifact_id=artifact.artifact_id,
            chart_type=artifact.chart_type,
            title=artifact.title,
            description=artifact.description,
            renderer=artifact.renderer,
            data_source="workflow_state",
            x_field="month",
            y_fields=["revenue"],
            row_count=2,
            series_count=1,
            category_count=2,
            summary_text="Revenue rises from 1200 in Jan to 1450 in Feb.",
            key_insights=["Revenue increased month over month."],
            data_ref="artifact://session_runtime_chart/chart_vis_001",
            metadata={"source": "workflow_state", "usecase": request.usecase},
        )
        contribution = build_chart_context_contribution(summary)

        artifacts = [artifact.model_dump(mode="python")]
        contributions = [contribution.model_dump(mode="python")]
        if bool(request.metadata.get("multi_artifact_test", False)):
            second_artifact = artifact.model_copy(
                update={
                    "artifact_id": "chart_vis_002",
                    "title": "Expense by Month",
                    "data_ref": "artifact://session_runtime_chart/chart_vis_002",
                    "data": [
                        {"month": "Jan", "revenue": 900},
                        {"month": "Feb", "revenue": 980},
                    ],
                }
            )
            second_summary = summary.model_copy(
                update={
                    "artifact_id": second_artifact.artifact_id,
                    "title": second_artifact.title,
                    "summary_text": "Expense rises from 900 in Jan to 980 in Feb.",
                    "data_ref": second_artifact.data_ref,
                }
            )
            artifacts.append(second_artifact.model_dump(mode="python"))
            contributions.append(build_chart_context_contribution(second_summary).model_dump(mode="python"))

        return build_run_result(
            status="completed",
            answer="Here is the revenue chart.",
            agent_name=self.name,
            llm_profile=request.llm_profile,
            artifacts=tuple(artifacts),
            context_contributions=tuple(contributions),
            metadata={
                "response_mode": "chart_generated",
                "artifact_count": len(artifacts),
                "context_contribution_count": len(contributions),
            },
        )