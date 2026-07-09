from __future__ import annotations

from pathlib import Path
import shutil

import yaml

from app.context import ToolRuntimeContext
from app.observability.logging import create_bootstrap_logger
from app.observability.metrics import InMemoryMetricsRecorder, MetricsRecorder
from app.observability.tracing import InMemoryTraceRecorder, TraceRecorder
from app.schemas import AppSettings
from app.security.redaction import Redactor
from app.security.secrets import EnvironmentSecretResolver
from app.services.clock import SystemClock
from app.services.http_client import HttpClientFactory
from app.services.rate_limit import DisabledRateLimiter


FIXTURE_TOOLS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tools"


def build_settings(*, tools: dict[str, object] | None = None) -> AppSettings:
    return AppSettings.model_validate(
        {
            "server": {
                "name": "main_mcp",
                "version": "1.0.0",
                "environment": "test",
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
                "inbound_auth": {"enabled": False, "mode": "none", "jwt": {}},
                "outbound_auth": {"default_mode": "none", "oauth_clients": {}},
                "tls": {"mode": "terminate_upstream", "behind_proxy": True},
                "secrets": {
                    "provider": "env",
                    "allow_tool_env_prefixes": ["MCP_TOOL_", "WEBSEARCH_"],
                },
            },
            "policy": {
                "default_tool_enabled": False,
                "expose_internal_tools": True,
                "expose_health_tool": True,
                "expose_capabilities_tool": True,
                "require_tool_manifest": True,
                "require_tool_config_validation": True,
                "reject_secret_like_arguments": True,
            },
            "observability": {
                "log_level": "INFO",
                "json_logs": True,
                "trace_headers": {
                    "inbound_trace_id": "x-trace-id",
                    "inbound_request_id": "x-request-id",
                },
                "redact_secrets": True,
                "metrics_enabled": True,
                "max_log_payload_chars": 2000,
            },
            "defaults": {
                "timeout_seconds": 30,
                "max_result_bytes": 262144,
                "max_argument_bytes": 65536,
                "max_results": 10,
                "rate_limit": {
                    "enabled": False,
                    "per_tool_per_minute": 60,
                },
            },
            "tools": tools or {},
        }
    )


def build_tool_context(
    *,
    tool_name: str,
    capability_name: str | None = None,
    tool_config: dict[str, object] | None = None,
    metrics: MetricsRecorder | None = None,
    tracer: TraceRecorder | None = None,
) -> ToolRuntimeContext:
    settings = build_settings()
    redactor = Redactor(max_string_length=settings.observability.max_log_payload_chars)
    logger = create_bootstrap_logger(redactor).bind(
        server_name=settings.server.name,
        tool_name=tool_name,
        capability_name=capability_name or tool_name,
    )
    secret_resolver = EnvironmentSecretResolver(settings.security.secrets, environ={})
    return ToolRuntimeContext(
        server_name=settings.server.name,
        environment=settings.server.environment,
        tool_name=tool_name,
        tool_config=dict(tool_config or {}),
        app_config=settings,
        logger=logger,
        redactor=redactor,
        secrets=secret_resolver.for_tools(),
        http_client_factory=HttpClientFactory(timeout_seconds=settings.defaults.timeout_seconds),
        auth=None,
        outbound_auth=None,
        rate_limiter=DisabledRateLimiter(),
        metrics=metrics or InMemoryMetricsRecorder(),
        tracer=tracer or InMemoryTraceRecorder(redactor=redactor),
        clock=SystemClock(),
    )


def copy_fixture_tool(tmp_path: Path, tool_name: str) -> Path:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_TOOLS_DIR / tool_name, tools_dir / tool_name)
    return tools_dir


def write_app_config(
    tmp_path: Path,
    *,
    tools_dir: Path,
    tools: dict[str, object] | None = None,
    metrics_enabled: bool = True,
) -> Path:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {
                    "name": "main_mcp",
                    "version": "1.0.0",
                    "environment": "test",
                    "host": "127.0.0.1",
                    "port": 9001,
                    "path": "/mcp",
                    "transport": "http",
                },
                "runtime": {
                    "tools_dir": tools_dir.as_posix(),
                    "discovery_on_startup": True,
                    "fail_on_required_tool_error": True,
                    "fail_on_optional_tool_error": False,
                },
                "security": {
                    "inbound_auth": {"enabled": False, "mode": "none"},
                    "outbound_auth": {"default_mode": "none"},
                    "tls": {"mode": "terminate_upstream", "behind_proxy": True},
                    "secrets": {
                        "provider": "env",
                        "allow_tool_env_prefixes": ["MCP_TOOL_", "WEBSEARCH_"],
                    },
                },
                "policy": {
                    "default_tool_enabled": False,
                    "expose_internal_tools": True,
                    "expose_health_tool": True,
                    "expose_capabilities_tool": True,
                    "require_tool_manifest": True,
                    "require_tool_config_validation": True,
                    "reject_secret_like_arguments": True,
                },
                "observability": {
                    "log_level": "INFO",
                    "json_logs": True,
                    "trace_headers": {
                        "inbound_trace_id": "x-trace-id",
                        "inbound_request_id": "x-request-id",
                    },
                    "redact_secrets": True,
                    "metrics_enabled": metrics_enabled,
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
                "tools": tools or {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path