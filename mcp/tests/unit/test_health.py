import json

from app.registry import ToolRegistry
from app.schemas import AppSettings
from app.health import build_health_payload


def _settings() -> AppSettings:
    return AppSettings.model_validate(
        {
            "server": {
                "name": "main_mcp",
                "version": "1.0.0",
                "environment": "local",
                "host": "127.0.0.1",
                "port": 9001,
                "path": "/mcp",
                "transport": "http",
            },
            "runtime": {
                "tools_dir": "mcp/tools",
                "discovery_on_startup": True,
                "fail_on_required_tool_error": True,
                "fail_on_optional_tool_error": False,
            },
            "security": {
                "inbound_auth": {
                    "enabled": False,
                    "mode": "none",
                    "bearer_token_env": "MCP_BEARER_TOKEN",
                    "jwt": {},
                },
                "outbound_auth": {
                    "default_mode": "none",
                    "oauth_clients": {},
                },
                "tls": {
                    "mode": "terminate_upstream",
                    "cert_file": "",
                    "key_file": "",
                    "behind_proxy": True,
                },
                "secrets": {
                    "provider": "env",
                    "allow_tool_env_prefixes": ["MCP_TOOL_", "WEBSEARCH_"],
                },
            },
            "policy": {"expose_health_tool": True},
            "observability": {
                "log_level": "INFO",
                "json_logs": True,
                "trace_headers": {},
                "redact_secrets": True,
                "metrics_enabled": False,
                "max_log_payload_chars": 2000,
            },
            "defaults": {
                "timeout_seconds": 30,
                "max_result_bytes": 262144,
                "max_argument_bytes": 65536,
                "max_results": 10,
                "rate_limit": {
                    "enabled": True,
                    "per_tool_per_minute": 60,
                },
            },
        }
    )


def test_health_payload_matches_expected_shape() -> None:
    payload = build_health_payload(
        _settings(),
        {
            "logging": "ready",
            "redaction": "ready",
            "credentials": "env",
            "http_client": "ready",
            "rate_limiter": "in-memory",
            "clock": "ready",
            "metrics": "in-memory",
            "tracing": "in-memory",
            "auth": "none",
            "outbound_auth": "none",
        },
        registry=ToolRegistry(),
    )

    assert payload == {
        "status": "ok",
        "ready": True,
        "server": {
            "name": "main_mcp",
            "version": "1.0.0",
            "environment": "local",
        },
        "tools": {
            "loaded": 0,
            "enabled": 0,
            "disabled": 0,
            "failed": 0,
            "unhealthy": 0,
        },
        "security": {
            "inbound_auth_enabled": False,
            "inbound_auth_mode": "none",
            "tls_mode": "terminate_upstream",
            "outbound_oauth_clients_configured": 0,
        },
        "config": {
            "server": {
                "name": "main_mcp",
                "version": "1.0.0",
                "environment": "local",
                "transport": "http",
                "path": "/mcp",
            },
            "runtime": {
                "tools_dir": "mcp/tools",
                "discovery_on_startup": True,
                "fail_on_required_tool_error": True,
                "fail_on_optional_tool_error": False,
                "reload_tools_in_dev": False,
            },
            "security": {
                "inbound_auth_enabled": False,
                "inbound_auth_mode": "none",
                "tls_mode": "terminate_upstream",
                "behind_proxy": True,
                "credential_provider": "env",
                "allowed_env_prefixes": ["MCP_TOOL_", "WEBSEARCH_"],
                "outbound_oauth_clients_configured": 0,
            },
            "observability": {
                "log_level": "INFO",
                "json_logs": True,
                "payload_redaction": True,
                "max_log_payload_chars": 2000,
            },
            "defaults": {
                "timeout_seconds": 30,
                "max_result_bytes": 262144,
                "max_argument_bytes": 65536,
                "max_results": 10,
                "rate_limit_enabled": True,
                "per_tool_per_minute": 60,
            },
            "tools": {},
        },
        "services": {
            "logging": "ready",
            "redaction": "ready",
            "credentials": "env",
            "http_client": "ready",
            "rate_limiter": "in-memory",
            "clock": "ready",
            "metrics": "in-memory",
            "tracing": "in-memory",
            "auth": "none",
            "outbound_auth": "none",
        },
        "checks": {
            "process_liveness": "ok",
            "config_loaded": "ok",
            "registry_loaded": "ok",
            "required_tools_loaded": "ok",
            "optional_failed_tools": "ok",
            "security_mode_valid": "ok",
            "websearch_local_readiness": "ok",
        },
    }


def test_health_payload_contains_no_secret_values_or_secret_keys() -> None:
    payload = build_health_payload(
        _settings(),
        {"credentials": "env"},
    )

    serialized = json.dumps(payload).lower()

    assert "token" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized
