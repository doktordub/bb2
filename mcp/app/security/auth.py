"""Inbound authentication services and FastMCP transport integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import hmac
from typing import Any, Protocol

from fastmcp.server.auth import AccessToken, AuthProvider
from fastmcp.server.dependencies import get_access_token, get_http_headers

from app.errors import MCPAuthError, MCPJWTValidationError, MCPSecretError
from app.observability.context import (
    REQUEST_ID_ALIAS_HEADER,
    REQUEST_ID_HEADER,
    TRACE_ID_ALIAS_HEADER,
    TRACE_ID_HEADER,
    resolve_incoming_request_id,
    resolve_incoming_trace_id,
)
from app.schemas import InboundAuthSettings
from app.security.jwt import JWTVerifierService
from app.security.scopes import normalize_scopes
from app.security.secrets import EnvironmentSecretResolver


AUTHORIZATION_HEADER = "authorization"
TRACE_HEADER_NAMES = (TRACE_ID_HEADER, TRACE_ID_ALIAS_HEADER)
REQUEST_HEADER_NAMES = (REQUEST_ID_HEADER, REQUEST_ID_ALIAS_HEADER)
CALLER_SERVICE_HEADER_NAMES = ("x-caller-service", "x-service-name", "x-client-service")


def _normalize_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_header(headers: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = headers.get(name)
        if value:
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _extract_request_metadata(headers: Mapping[str, str]) -> tuple[str | None, str | None, str | None]:
    normalized_headers = {
        str(key).strip().lower(): str(value).strip()
        for key, value in headers.items()
        if str(key).strip() and value is not None
    }
    return (
        resolve_incoming_trace_id(normalized_headers),
        resolve_incoming_request_id(normalized_headers),
        _first_header(normalized_headers, CALLER_SERVICE_HEADER_NAMES),
    )


def _extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    value = headers.get(AUTHORIZATION_HEADER)
    if value is None:
        return None

    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("invalid_authorization_header", "Authentication failed.")
    return token.strip()


class AuthError(MCPAuthError):
    """Safe authentication error surfaced to MCP callers."""

    def __init__(self, code: str, public_message: str = "Authentication failed.") -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


@dataclass(frozen=True, slots=True)
class InboundRequestContext:
    """Safe request identity information exposed to plugins."""

    trace_id: str | None
    request_id: str | None
    caller_service: str | None
    authenticated: bool
    auth_subject: str | None
    auth_scopes: tuple[str, ...]


class AuthVerifier(Protocol):
    """Minimal contract shared by bearer and JWT verification modes."""

    @property
    def enabled(self) -> bool:
        ...

    @property
    def mode_name(self) -> str:
        ...

    def verify_token(
        self,
        token: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> InboundRequestContext:
        ...


@dataclass(frozen=True, slots=True)
class NoopAuthVerifier:
    """Disabled auth verifier for local development profiles."""

    enabled: bool = False
    mode_name: str = "none"

    def verify_token(
        self,
        token: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> InboundRequestContext:
        del token, headers
        raise AuthError("auth_disabled", "Authentication is not enabled.")


@dataclass(frozen=True, slots=True)
class BearerAuthVerifier:
    """Constant-time bearer token verification backed by the secret resolver."""

    settings: InboundAuthSettings
    secret_resolver: EnvironmentSecretResolver
    enabled: bool = True
    mode_name: str = "bearer"

    def verify_token(
        self,
        token: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> InboundRequestContext:
        trace_id, request_id, caller_service = _extract_request_metadata(headers or {})

        try:
            expected_token = self.secret_resolver.get(
                "mcp_bearer_token",
                env_var=self.settings.bearer_token_env,
                required=True,
            )
        except MCPSecretError as error:
            raise AuthError("auth_unavailable", "Authentication failed.") from error

        assert expected_token is not None
        if not hmac.compare_digest(token, expected_token.get_secret_value()):
            raise AuthError("invalid_token", "Authentication failed.")

        subject = caller_service or "bearer-client"
        return InboundRequestContext(
            trace_id=trace_id,
            request_id=request_id,
            caller_service=caller_service,
            authenticated=True,
            auth_subject=subject,
            auth_scopes=(),
        )


@dataclass(frozen=True, slots=True)
class JWTAuthVerifier:
    """JWT verifier wrapper that returns a scrubbed request identity."""

    jwt_verifier: JWTVerifierService
    enabled: bool = True
    mode_name: str = "jwt"

    def verify_token(
        self,
        token: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> InboundRequestContext:
        trace_id, request_id, caller_service = _extract_request_metadata(headers or {})
        try:
            identity = self.jwt_verifier.verify_token(token)
        except MCPJWTValidationError as error:
            raise AuthError("invalid_token", "Authentication failed.") from error

        return InboundRequestContext(
            trace_id=trace_id,
            request_id=request_id,
            caller_service=caller_service or identity.caller_service,
            authenticated=True,
            auth_subject=identity.subject,
            auth_scopes=identity.scopes,
        )


@dataclass(slots=True)
class InboundAuthService:
    """Shared inbound auth service used by bootstrap, FastMCP, and plugins."""

    verifier: AuthVerifier

    @property
    def enabled(self) -> bool:
        return self.verifier.enabled

    @property
    def mode_name(self) -> str:
        return self.verifier.mode_name

    def build_auth_provider(self, *, base_url: str | None) -> AuthProvider | None:
        if not self.enabled or self.mode_name == "none":
            return None
        return _TransportAuthProvider(verifier=self.verifier, base_url=base_url)

    def current_request_context(self, *, require_authenticated: bool = False) -> InboundRequestContext:
        headers = get_http_headers(
            include={
                AUTHORIZATION_HEADER,
                *TRACE_HEADER_NAMES,
                *REQUEST_HEADER_NAMES,
                *CALLER_SERVICE_HEADER_NAMES,
            }
        )
        trace_id, request_id, caller_service = _extract_request_metadata(headers)
        access_token = get_access_token()

        if access_token is not None:
            auth_subject = _normalize_text(access_token.subject) or _normalize_text(
                access_token.client_id
            )
            resolved_caller_service = caller_service or _normalize_text(access_token.client_id)
            return InboundRequestContext(
                trace_id=trace_id,
                request_id=request_id,
                caller_service=resolved_caller_service,
                authenticated=True,
                auth_subject=auth_subject,
                auth_scopes=normalize_scopes(access_token.scopes),
            )

        if self.enabled and require_authenticated:
            token = _extract_bearer_token(headers)
            if token is None:
                raise AuthError("authentication_required", "Authentication required.")
            return self.verifier.verify_token(token, headers=headers)

        return InboundRequestContext(
            trace_id=trace_id,
            request_id=request_id,
            caller_service=caller_service,
            authenticated=False,
            auth_subject=None,
            auth_scopes=(),
        )


class _TransportAuthProvider(AuthProvider):
    """FastMCP auth provider that delegates verification to the MCP auth service."""

    def __init__(self, *, verifier: AuthVerifier, base_url: str | None) -> None:
        super().__init__(base_url=base_url)
        self._verifier = verifier

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            request_context = await asyncio.to_thread(self._verifier.verify_token, token)
        except MCPAuthError:
            return None

        claims: dict[str, Any] = {}
        if request_context.auth_subject is not None:
            claims["sub"] = request_context.auth_subject
        if request_context.caller_service is not None:
            claims["client_id"] = request_context.caller_service
        if request_context.auth_scopes:
            claims["scope"] = " ".join(request_context.auth_scopes)

        return AccessToken(
            token=token,
            client_id=request_context.caller_service
            or request_context.auth_subject
            or "authenticated-client",
            scopes=list(request_context.auth_scopes),
            subject=request_context.auth_subject,
            claims=claims,
        )


def create_auth_service(
    settings: InboundAuthSettings,
    secret_resolver: EnvironmentSecretResolver,
) -> InboundAuthService:
    """Create the shared inbound auth service for the configured auth mode."""

    if not settings.enabled or settings.mode == "none":
        return InboundAuthService(verifier=NoopAuthVerifier())

    if settings.mode == "bearer":
        if not settings.bearer_token_env:
            raise MCPAuthError("Bearer authentication requires bearer_token_env.")
        secret_resolver.get(
            "mcp_bearer_token",
            env_var=settings.bearer_token_env,
            required=True,
        )
        return InboundAuthService(
            verifier=BearerAuthVerifier(
                settings=settings,
                secret_resolver=secret_resolver,
            )
        )

    if settings.mode == "jwt":
        return InboundAuthService(verifier=JWTAuthVerifier(JWTVerifierService(settings.jwt)))

    raise MCPAuthError(f"Unsupported inbound auth mode: {settings.mode!r}")