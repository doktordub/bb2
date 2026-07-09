from __future__ import annotations

import json

from app.bootstrap import bootstrap
from app.observability.events import MCP_CONFIG_LOADED
from tests.unit.observability.support import copy_fixture_tool, write_app_config


def test_startup_diagnostics_are_safe_and_useful(tmp_path) -> None:
    tools_dir = copy_fixture_tool(tmp_path, "valid_tool")
    config_path = write_app_config(
        tmp_path,
        tools_dir=tools_dir,
        tools={
            "valid_tool": {
                "enabled": True,
                "required": True,
            }
        },
    )
    runtime = bootstrap(config_path)

    startup_events = [
        event for event in runtime.services.tracer.events if event.event_name == MCP_CONFIG_LOADED
    ]
    assert len(startup_events) == 1

    payload = startup_events[0].payload
    assert payload["config_loaded"] is True
    assert payload["server_name"] == "main_mcp"
    assert payload["server_version"] == "1.0.0"
    assert payload["environment"] == "test"
    assert payload["enabled_tool_count"] == 1
    assert payload["disabled_tool_count"] == 0
    assert payload["failed_optional_tool_count"] == 0
    assert payload["inbound_auth_mode"] == "none"
    assert payload["tls_mode"] == "terminate_upstream"

    serialized = json.dumps(payload).lower()
    assert "token" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized