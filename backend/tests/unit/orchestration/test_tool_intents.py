from __future__ import annotations

from app.contracts.tools import ToolDefinition
from app.orchestration.tool_intents import build_tool_policy_metadata, resolve_tool_intent, tool_result_safe_text
from app.contracts.tools import ToolExecutionResult, ToolResultContent, ToolResultSummary


def test_resolve_tool_intent_uses_first_allowed_logical_tool() -> None:
    intent = resolve_tool_intent(
        "tool: architecture notes",
        allowed_tool_names=["mcp:raw_tool", "documents.search"],
    )

    assert intent is not None
    assert intent.tool_name == "documents.search"
    assert intent.arguments == {"query": "architecture notes", "limit": 3}


def test_build_tool_policy_metadata_exposes_only_safe_tool_fields() -> None:
    metadata = build_tool_policy_metadata(
        ToolDefinition(
            name="documents.search",
            description="Search indexed documents.",
            execution_modes=("sync", "stream"),
            safety_level="read_only",
            approval_required=False,
            metadata={"unsafe": "kept"},
        )
    )

    assert metadata["tool_known"] is True
    assert metadata["tool_supports_streaming"] is True
    assert metadata["tool_safety_level"] == "read_only"


def test_tool_result_safe_text_prefers_summary_then_content() -> None:
    result = ToolExecutionResult(
        tool_name="documents.search",
        status="completed",
        content=[ToolResultContent(type="text", text="Found notes")],
        summary=ToolResultSummary(safe_message="Summary first"),
    )

    assert tool_result_safe_text(result) == "Summary first"