from app.contracts.errors import (
    MCPAuthenticationError,
    MCPDiscoveryError,
    MCPTransportError,
    PolicyDeniedError,
    ToolArgumentValidationError,
    ToolCancelledError,
    ToolDisabledError,
    ToolGatewayError,
    ToolNotFoundError,
    ToolPolicyDeniedError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)
from app.contracts.tools import (
    ToolCallRequest,
    ToolCapabilitiesResult,
    ToolCapabilitySummary,
    ToolDefinition,
    ToolErrorDetail,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealthResult,
    ToolListFilters,
    ToolListResult,
    ToolResult,
    ToolResultContent,
    ToolResultSummary,
    ToolScopes,
    ToolSpec,
    ToolStreamEvent,
)


def test_tool_scopes_and_filters_normalize_extended_fields() -> None:
    scopes = ToolScopes(
        user_id=" user-1 ",
        session_id=" session-1 ",
        tool_group=" retrieval ",
        tags=[" search ", "phase-2"],
        metadata={"reason": "test"},
    )
    filters = ToolListFilters(
        names=[" documents.search "],
        tags=[" search "],
        safety_levels=["read_only"],
        execution_mode="stream",
        name_prefix=" documents.",
    )

    assert scopes.has_explicit_scope() is True
    assert scopes.has_durable_scope() is True
    assert scopes.summary() == {
        "user_id_present": True,
        "project_id_present": False,
        "tenant_id_present": False,
        "session_id_present": True,
        "agent_name_present": False,
        "usecase_present": False,
        "tool_group_present": True,
        "tag_count": 2,
    }
    assert filters.names == ("documents.search",)
    assert filters.tags == ("search",)
    assert filters.safety_levels == ("read_only",)
    assert filters.execution_mode == "stream"
    assert filters.name_prefix == "documents."


def test_tool_definition_and_list_result_are_provider_neutral() -> None:
    tool = ToolDefinition(
        name=" documents.search ",
        description=" Search project documents ",
        input_schema={"type": "object"},
        source=" fake ",
        display_name="Search Documents",
        execution_modes=["sync", "stream"],
        safety_level="read_only",
        tags=["retrieval"],
        permissions=["project.read"],
    )
    compatibility_tool = ToolSpec(
        name="filesystem.read_project_file",
        description="Read one project file",
        input_schema={"type": "object"},
        source="fake",
    )
    listed = ToolListResult(tools=[tool, compatibility_tool], metadata={"provider": "fake"})

    assert tool.name == "documents.search"
    assert tool.source == "fake"
    assert tool.supports_streaming is True
    assert tool.tags == ("retrieval",)
    assert tool.permissions == ("project.read",)
    assert compatibility_tool.name == "filesystem.read_project_file"
    assert listed.total_count == 2
    assert listed == [tool, compatibility_tool]


def test_tool_execution_models_support_compatibility_aliases() -> None:
    request = ToolExecutionRequest(
        tool_name=" documents.search ",
        arguments={"query": "policy"},
        scopes={"project_id": " proj-1 "},
        timeout_seconds=5,
        idempotency_key=" idem-1 ",
        metadata={"agent_name": "planner"},
    )
    compatibility_request = ToolCallRequest(
        tool_name="documents.search",
        arguments={"query": "policy"},
    )
    result = ToolExecutionResult(
        tool_name="documents.search",
        status="completed",
        content=[ToolResultContent(type="json", json_value={"hits": 1})],
        structured_content={"hits": 1},
        summary=ToolResultSummary(
            result_count=1,
            bytes_returned=128,
            safe_message="1 hit returned.",
        ),
        metadata={"provider": "fake"},
    )
    compatibility_result = ToolResult(
        tool_name="documents.search",
        status="failed",
        error_detail=ToolErrorDetail(
            code="tool_disabled",
            message="Tool is disabled.",
        ),
        summary=ToolResultSummary(safe_message="Tool is disabled."),
    )

    assert request.tool_name == "documents.search"
    assert request.scopes.project_id == "proj-1"
    assert compatibility_request.scopes.has_explicit_scope() is False
    assert result.success is True
    assert result.data == {"hits": 1}
    assert compatibility_result.success is False
    assert compatibility_result.error == "Tool is disabled."


def test_tool_stream_health_capabilities_and_errors_are_safe_and_typed() -> None:
    definition = ToolDefinition(
        name="documents.search",
        description="Search project documents",
        input_schema={"type": "object"},
        display_name="Search Documents",
        execution_modes=["sync", "stream"],
    )
    capability = ToolCapabilitySummary.from_definition(definition)
    result = ToolExecutionResult(
        tool_name="documents.search",
        status="completed",
        content=[ToolResultContent(type="text", text="Found 1 document.")],
    )
    started = ToolStreamEvent.started(tool_name="documents.search")
    completed = ToolStreamEvent.completed(tool_name="documents.search", result=result)
    health = ToolHealthResult(
        status="ok",
        tooling_enabled=True,
        mcp_configured=True,
        mcp_status="ok",
        tools_configured=2,
        tools_discovered=2,
        tools_enabled=1,
        registry_status="ok",
    )
    capabilities = ToolCapabilitiesResult(
        enabled=True,
        mcp_configured=True,
        streaming_supported=True,
        available_logical_tools=[capability],
    )

    assert started.type == "started"
    assert completed.result is result
    assert health["mcp_status"] == "ok"
    assert capabilities["available_logical_tools"][0]["name"] == "documents.search"
    assert issubclass(ToolNotFoundError, ToolGatewayError)
    assert issubclass(ToolDisabledError, ToolGatewayError)
    assert issubclass(ToolArgumentValidationError, ToolGatewayError)
    assert issubclass(ToolPolicyDeniedError, PolicyDeniedError)
    assert issubclass(ToolPolicyDeniedError, ToolGatewayError)
    assert issubclass(ToolTimeoutError, ToolGatewayError)
    assert issubclass(ToolCancelledError, ToolGatewayError)
    assert issubclass(ToolResultTooLargeError, ToolGatewayError)
    assert issubclass(MCPAuthenticationError, ToolGatewayError)
    assert issubclass(MCPTransportError, ToolGatewayError)
    assert issubclass(MCPDiscoveryError, ToolGatewayError)