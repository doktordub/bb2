from __future__ import annotations

from dataclasses import replace

from app.health import build_health_payload
from app.registry import ToolRegistry
from tests.unit.observability.support import build_settings


def test_readiness_fails_when_required_tool_fails() -> None:
    settings = build_settings(
        tools={
            "websearch": {
                "enabled": True,
                "required": True,
                "config_file": "config.yaml",
            }
        }
    )
    registry = ToolRegistry()
    registry.register_failed("websearch", RuntimeError("boom"), required=True)

    payload = build_health_payload(settings, registry=registry)

    assert payload["status"] == "unhealthy"
    assert payload["ready"] is False
    assert payload["checks"]["required_tools_loaded"] == "unhealthy"
    assert payload["checks"]["websearch_local_readiness"] == "unhealthy"


def test_readiness_degrades_when_optional_tool_fails() -> None:
    settings = build_settings(
        tools={
            "optional_demo": {
                "enabled": True,
                "required": False,
            }
        }
    )
    registry = ToolRegistry()
    registry.register_failed("optional_demo", RuntimeError("boom"), required=False)

    payload = build_health_payload(settings, registry=registry)

    assert payload["status"] == "degraded"
    assert payload["ready"] is True
    assert payload["checks"]["optional_failed_tools"] == "degraded"


def test_readiness_fails_when_required_tool_is_loaded_but_unhealthy() -> None:
    settings = build_settings(
        tools={
            "reporting": {
                "enabled": True,
                "required": True,
            }
        }
    )
    registry = ToolRegistry()
    registry.register_failed("reporting", RuntimeError("startup placeholder"), required=True)
    registry._tools["reporting"] = replace(
        registry._tools["reporting"],
        load_status="loaded",
        health_status="degraded",
    )

    payload = build_health_payload(settings, registry=registry)

    assert payload["status"] == "degraded"
    assert payload["ready"] is False
    assert payload["checks"]["required_tools_loaded"] == "degraded"


def test_readiness_degrades_when_optional_tool_is_loaded_but_unhealthy() -> None:
    settings = build_settings(
        tools={
            "reporting": {
                "enabled": True,
                "required": False,
            }
        }
    )
    registry = ToolRegistry()
    registry.register_failed("reporting", RuntimeError("startup placeholder"), required=False)
    registry._tools["reporting"] = replace(
        registry._tools["reporting"],
        load_status="loaded",
        health_status="degraded",
    )

    payload = build_health_payload(settings, registry=registry)

    assert payload["status"] == "degraded"
    assert payload["ready"] is True
    assert payload["checks"]["optional_failed_tools"] == "degraded"