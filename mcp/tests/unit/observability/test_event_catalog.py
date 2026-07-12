from __future__ import annotations

from app.observability.events import EVENT_NAMES, all_event_names


EXPECTED_EVENT_NAMES = {
    "mcp_startup_started",
    "mcp_config_loaded",
    "mcp_config_invalid",
    "mcp_tool_discovery_started",
    "mcp_tool_manifest_loaded",
    "mcp_tool_config_loaded",
    "mcp_tool_registered",
    "mcp_tool_registration_failed",
    "mcp_tool_call_started",
    "mcp_tool_call_completed",
    "mcp_tool_call_failed",
    "mcp_tool_call_timeout",
    "mcp_tool_call_cancelled",
    "mcp_health_checked",
    "mcp_reporting_query_started",
    "mcp_reporting_request_validated",
    "mcp_reporting_provider_call_started",
    "mcp_reporting_provider_call_completed",
    "mcp_reporting_provider_call_failed",
    "mcp_reporting_result_normalized",
    "mcp_reporting_result_truncated",
    "mcp_shutdown_started",
    "mcp_shutdown_completed",
}


def test_event_names_are_unique() -> None:
    assert len(EVENT_NAMES) == len(set(EVENT_NAMES))


def test_event_catalog_is_complete() -> None:
    assert set(all_event_names()) == EXPECTED_EVENT_NAMES