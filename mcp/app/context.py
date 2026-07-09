"""Shared runtime container for MCP common services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastmcp.server.auth import AuthProvider

from app.observability.logging import StructuredLogger
from app.observability.metrics import MetricsRecorder
from app.observability.tracing import TraceRecorder
from app.schemas import AppSettings
from app.security.redaction import Redactor
from app.security.secrets import EnvironmentSecretResolver, SecretResolver
from app.services.clock import Clock
from app.services.http_client import HttpClientFactory
from app.services.rate_limit import RateLimiter


class AuthService(Protocol):
    """Shared inbound auth surface available to tool plugins and server wiring."""

    @property
    def enabled(self) -> bool:
        ...

    @property
    def mode_name(self) -> str:
        ...

    def build_auth_provider(self, *, base_url: str | None) -> AuthProvider | None:
        ...

    def current_request_context(self, *, require_authenticated: bool = False) -> Any:
        ...


class OutboundAuthService(Protocol):
    """Shared outbound auth surface available to tool plugins."""

    @property
    def mode_name(self) -> str:
        ...

    @property
    def configured_clients(self) -> int:
        ...

    async def get_access_token(self, client_name: str) -> str:
        ...


@dataclass(frozen=True, slots=True)
class ToolRuntimeContext:
    """Shared runtime context passed to each tool plugin instance."""

    server_name: str
    environment: str
    tool_name: str
    tool_config: dict[str, Any]
    app_config: AppSettings
    logger: StructuredLogger
    redactor: Redactor
    secrets: SecretResolver
    http_client_factory: HttpClientFactory
    auth: AuthService | None
    outbound_auth: OutboundAuthService | None
    rate_limiter: RateLimiter
    metrics: MetricsRecorder
    tracer: TraceRecorder
    clock: Clock


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    """Holds validated settings and shared common services."""

    settings: AppSettings
    redactor: Redactor
    logger: StructuredLogger
    secret_resolver: EnvironmentSecretResolver
    http_client_factory: HttpClientFactory
    rate_limiter: RateLimiter
    clock: Clock
    metrics: MetricsRecorder
    tracer: TraceRecorder
    tool_secret_resolver: SecretResolver
    auth_service: AuthService | None = None
    outbound_auth_service: OutboundAuthService | None = None

    def readiness_summary(self) -> dict[str, str]:
        return {
            "logging": "ready",
            "redaction": "ready",
            "credentials": self.secret_resolver.provider_name,
            "http_client": "ready",
            "rate_limiter": self.rate_limiter.mode_name,
            "clock": "ready",
            "metrics": self.metrics.mode_name,
            "tracing": self.tracer.mode_name,
            "auth": self.auth_service.mode_name if self.auth_service is not None else "disabled",
            "outbound_auth": (
                self.outbound_auth_service.mode_name
                if self.outbound_auth_service is not None
                else "disabled"
            ),
        }

    def build_tool_runtime_context(
        self,
        *,
        tool_name: str,
        tool_config: dict[str, Any],
        auth: AuthService | None = None,
        outbound_auth: OutboundAuthService | None = None,
        metrics: MetricsRecorder | None = None,
        tracer: TraceRecorder | None = None,
    ) -> ToolRuntimeContext:
        return ToolRuntimeContext(
            server_name=self.settings.server.name,
            environment=self.settings.server.environment,
            tool_name=tool_name,
            tool_config=dict(tool_config),
            app_config=self.settings,
            logger=self.logger.bind(
                server_name=self.settings.server.name,
                tool_name=tool_name,
            ),
            redactor=self.redactor,
            secrets=self.tool_secret_resolver,
            http_client_factory=self.http_client_factory,
            auth=self.auth_service if auth is None else auth,
            outbound_auth=(
                self.outbound_auth_service if outbound_auth is None else outbound_auth
            ),
            rate_limiter=self.rate_limiter,
            metrics=self.metrics if metrics is None else metrics,
            tracer=self.tracer if tracer is None else tracer,
            clock=self.clock,
        )