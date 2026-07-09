"""Composition root for the MCP server."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from app.config import load_settings, redacted_settings_summary
from app.context import ServiceContainer
from app.errors import MCPConfigurationError
from app.loader import ToolLoader
from app.observability.events import MCP_CONFIG_INVALID, MCP_CONFIG_LOADED, MCP_STARTUP_STARTED
from app.observability.logging import (
    configure_runtime_logger,
    create_bootstrap_logger,
    emit_observability_event,
)
from app.observability.metrics import InMemoryMetricsRecorder, NoopMetricsRecorder
from app.observability.tracing import InMemoryTraceRecorder
from app.registry import ToolRegistry
from app.schemas import AppSettings
from app.security.auth import create_auth_service
from app.security.oauth import create_outbound_auth_service
from app.security.redaction import Redactor
from app.security.secrets import EnvironmentSecretResolver
from app.security.tls import summarize_tls_settings
from app.server import build_server, register_internal_tools
from app.services.clock import SystemClock
from app.services.http_client import HttpClientFactory
from app.services.rate_limit import DisabledRateLimiter, InMemoryRateLimiter, RateLimiter


CONFIG_RELATIVE_PATH = Path("config") / "app.yaml"


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    config_path: Path
    settings: AppSettings
    services: ServiceContainer
    registry: ToolRegistry
    server: FastMCP

    @property
    def config(self) -> dict[str, Any]:
        return self.settings.model_dump(mode="python")


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).resolve()

    return Path(__file__).resolve().parents[1] / CONFIG_RELATIVE_PATH


def bootstrap(config_path: str | Path | None = None) -> BootstrapResult:
    resolved_path = resolve_config_path(config_path)
    bootstrap_logger = create_bootstrap_logger()
    bootstrap_logger.info(MCP_STARTUP_STARTED, payload={"config_path": str(resolved_path)})

    try:
        settings = load_settings(resolved_path)
    except MCPConfigurationError as error:
        bootstrap_logger.error(
            MCP_CONFIG_INVALID,
            payload={
                "config_path": str(resolved_path),
                "error_code": error.__class__.__name__,
            },
        )
        raise
    redactor = Redactor(max_string_length=settings.observability.max_log_payload_chars)
    logger = configure_runtime_logger(settings.observability, redactor)
    clock = SystemClock()
    tracer = InMemoryTraceRecorder(redactor=redactor)
    metrics = (
        InMemoryMetricsRecorder()
        if settings.observability.metrics_enabled
        else NoopMetricsRecorder()
    )

    if settings.security.secrets.provider != "env":
        raise MCPConfigurationError(
            "Only the environment-backed secret resolver is implemented in phase 2."
        )

    secret_resolver = EnvironmentSecretResolver(
        settings=settings.security.secrets,
        environ=os.environ,
    )
    auth_service = create_auth_service(settings.security.inbound_auth, secret_resolver)
    http_client_factory = HttpClientFactory(timeout_seconds=settings.defaults.timeout_seconds)
    outbound_auth_service = create_outbound_auth_service(
        settings=settings.security.outbound_auth,
        secret_resolver=secret_resolver,
        http_client_factory=http_client_factory,
        clock=clock,
        logger=logger,
    )
    rate_limiter: RateLimiter
    if settings.defaults.rate_limit.enabled:
        rate_limiter = InMemoryRateLimiter(
            limit_per_minute=settings.defaults.rate_limit.per_tool_per_minute,
            clock=clock,
        )
    else:
        rate_limiter = DisabledRateLimiter()

    services = ServiceContainer(
        settings=settings,
        redactor=redactor,
        logger=logger,
        secret_resolver=secret_resolver,
        http_client_factory=http_client_factory,
        rate_limiter=rate_limiter,
        clock=clock,
        metrics=metrics,
        tracer=tracer,
        tool_secret_resolver=secret_resolver.for_tools(),
        auth_service=auth_service,
        outbound_auth_service=outbound_auth_service,
    )

    server = build_server(services)
    registry = ToolRegistry()
    loader = ToolLoader(
        config_path=resolved_path,
        settings=settings,
        services=services,
    )
    tools_dir = loader.resolve_tools_dir()

    if settings.runtime.discovery_on_startup:
        loader.load_tools(server, registry)

    register_internal_tools(server, services, registry)
    emit_observability_event(
        logger,
        tracer,
        MCP_CONFIG_LOADED,
        payload=_build_startup_diagnostics_payload(
            settings=settings,
            services=services,
            registry=registry,
            tools_dir=tools_dir,
        ),
    )
    return BootstrapResult(
        config_path=resolved_path,
        settings=settings,
        services=services,
        registry=registry,
        server=server,
    )


def _build_startup_diagnostics_payload(
    *,
    settings: AppSettings,
    services: ServiceContainer,
    registry: ToolRegistry,
    tools_dir: Path,
) -> dict[str, Any]:
    health_summary = registry.health_summary()
    failed_optional_tool_count = sum(
        1
        for tool in registry.list_tools()
        if (not tool.required) and tool.load_status == "failed"
    )
    return {
        "config_loaded": True,
        "server_name": settings.server.name,
        "server_version": settings.server.version,
        "environment": settings.server.environment,
        "tools_directory": str(tools_dir),
        "enabled_tool_count": health_summary.enabled,
        "disabled_tool_count": health_summary.disabled,
        "failed_optional_tool_count": failed_optional_tool_count,
        "inbound_auth_mode": settings.security.inbound_auth.mode,
        "tls_mode": settings.security.tls.mode,
        "services": services.readiness_summary(),
        "config": redacted_settings_summary(settings),
        "tls": summarize_tls_settings(settings.security.tls),
    }
