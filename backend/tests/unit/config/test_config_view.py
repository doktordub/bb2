from collections.abc import Mapping

import pytest

from app.config.redaction import REDACTED_VALUE
from app.config.view import (
    HealthSettings,
    ObservabilitySettings,
    ValidatedConfigurationView,
    get_health_settings,
    get_observability_settings,
)
from app.contracts.errors import ConfigurationError


def build_view() -> ValidatedConfigurationView:
    return ValidatedConfigurationView(
        {
            "app": {
                "environment": "local",
                "active_usecase": "support_chat",
            },
            "llm": {
                "providers": {
                    "openai": {
                        "api_key": "top-secret-key",
                    }
                },
                "profiles": {
                    "cloud_fast": {
                        "fallback_profiles": ["local_reasoning"],
                    }
                },
            },
            "observability": {
                "log_level": "DEBUG",
                "structured_logging": True,
                "trace_enabled": True,
                "trace_payloads_enabled": False,
                "trace_store_required": True,
                "redact_secrets": True,
                "include_stack_traces_in_logs": False,
                "include_stack_traces_in_traces": False,
                "max_trace_payload_chars": 4096,
                "slow_request_ms": 2500,
                "slow_llm_call_ms": 15000,
                "slow_tool_call_ms": 5000,
                "metrics_enabled": True,
            },
            "health": {
                "expose_config_summary": True,
                "expose_provider_names": True,
                "expose_secret_values": False,
                "include_component_details": True,
            },
        }
    )


def test_validated_config_view_get_require_and_section() -> None:
    view = build_view()

    assert view.get("app.environment") == "local"
    assert view.get("app.missing", "fallback") == "fallback"
    assert view.require("app.active_usecase") == "support_chat"
    assert view.section("llm") == {
        "providers": {"openai": {"api_key": "top-secret-key"}},
        "profiles": {"cloud_fast": {"fallback_profiles": ["local_reasoning"]}},
    }


def test_validated_config_view_is_immutable() -> None:
    view = build_view()

    llm_section = view.get("llm")
    fallback_profiles = view.require("llm.profiles.cloud_fast.fallback_profiles")

    assert isinstance(llm_section, Mapping)
    assert fallback_profiles == ("local_reasoning",)

    with pytest.raises(TypeError):
        llm_section["providers"] = {}  # type: ignore[index]

    with pytest.raises(AttributeError):
        fallback_profiles.append("another-profile")  # type: ignore[attr-defined]


def test_validated_config_view_raises_path_safe_errors() -> None:
    view = build_view()

    with pytest.raises(ConfigurationError, match="Missing required config path: app.missing"):
        view.require("app.missing")

    with pytest.raises(ConfigurationError, match="Config path is not a section: app.environment"):
        view.section("app.environment")


def test_validated_config_view_redacted_dump_masks_secrets() -> None:
    view = build_view()

    assert view.as_redacted_dict() == {
        "app": {
            "environment": "local",
            "active_usecase": "support_chat",
        },
        "llm": {
            "providers": {
                "openai": {
                    "api_key": REDACTED_VALUE,
                }
            },
            "profiles": {
                "cloud_fast": {
                    "fallback_profiles": ["local_reasoning"],
                }
            },
        },
        "observability": {
            "log_level": "DEBUG",
            "structured_logging": True,
            "trace_enabled": True,
            "trace_payloads_enabled": False,
            "trace_store_required": True,
            "redact_secrets": True,
            "include_stack_traces_in_logs": False,
            "include_stack_traces_in_traces": False,
            "max_trace_payload_chars": 4096,
            "slow_request_ms": 2500,
            "slow_llm_call_ms": 15000,
            "slow_tool_call_ms": 5000,
            "metrics_enabled": True,
        },
        "health": {
            "expose_config_summary": True,
            "expose_provider_names": True,
            "expose_secret_values": False,
            "include_component_details": True,
        },
    }


def test_validated_config_view_observability_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = ObservabilitySettings(
        log_level="DEBUG",
        structured_logging=True,
        trace_enabled=True,
        trace_payloads_enabled=False,
        trace_store_required=True,
        redact_secrets=True,
        include_stack_traces_in_logs=False,
        include_stack_traces_in_traces=False,
        max_trace_payload_chars=4096,
        slow_request_ms=2500,
        slow_llm_call_ms=15000,
        slow_tool_call_ms=5000,
        metrics_enabled=True,
    )

    assert get_observability_settings(view) == expected
    assert view.observability_settings() == expected


def test_validated_config_view_health_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = HealthSettings(
        expose_config_summary=True,
        expose_provider_names=True,
        expose_secret_values=False,
        include_component_details=True,
    )

    assert get_health_settings(view) == expected
    assert view.health_settings() == expected