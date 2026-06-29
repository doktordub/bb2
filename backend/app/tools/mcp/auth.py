"""MCP authentication providers and safe header construction."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

from app.config.view import MCPAuthSettings
from app.tools.errors import MCPAuthenticationError, ToolingConfigurationError

_TOKEN_REFRESH_SKEW_SECONDS = 30

HttpxAsyncClientFactory = Callable[..., httpx.AsyncClient]


class MCPAuthProvider(Protocol):
    """Backend-owned auth provider for outgoing MCP requests."""

    async def get_headers(self) -> dict[str, str]:
        ...


class NoOpMCPAuthProvider:
    """Return no auth headers for local or unauthenticated MCP servers."""

    async def get_headers(self) -> dict[str, str]:
        return {}


class StaticTokenMCPAuthProvider:
    """Return a static bearer-style Authorization header."""

    def __init__(self, token: str, *, scheme: str = "Bearer") -> None:
        normalized_token = token.strip()
        if not normalized_token:
            raise ToolingConfigurationError("Static MCP auth requires a non-empty token.")
        normalized_scheme = scheme.strip() or "Bearer"
        self._token = normalized_token
        self._scheme = normalized_scheme

    async def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"{self._scheme} {self._token}"}


@dataclass(slots=True)
class _CachedOAuthToken:
    access_token: str
    token_type: str
    expires_at: datetime | None


class OAuthClientCredentialsMCPAuthProvider:
    """Fetch and cache OAuth client-credentials tokens for MCP requests."""

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: tuple[str, ...] = (),
        timeout_seconds: int = 10,
        client_factory: HttpxAsyncClientFactory | None = None,
    ) -> None:
        self._token_url = _required_text(token_url, "OAuth token URL is required.")
        self._client_id = _required_text(client_id, "OAuth client ID is required.")
        self._client_secret = _required_text(
            client_secret,
            "OAuth client secret is required.",
        )
        self._scopes = tuple(scope for scope in (_normalized_text(item) for item in scopes) if scope)
        self._timeout_seconds = max(1, timeout_seconds)
        self._client_factory = client_factory or httpx.AsyncClient
        self._lock = asyncio.Lock()
        self._cached_token: _CachedOAuthToken | None = None

    async def get_headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"{token.token_type} {token.access_token}"}

    async def _get_token(self) -> _CachedOAuthToken:
        cached = self._cached_token
        if cached is not None and _token_is_fresh(cached):
            return cached

        async with self._lock:
            cached = self._cached_token
            if cached is not None and _token_is_fresh(cached):
                return cached
            refreshed = await self._fetch_token()
            self._cached_token = refreshed
            return refreshed

    async def _fetch_token(self) -> _CachedOAuthToken:
        form_data = {"grant_type": "client_credentials"}
        if self._scopes:
            form_data["scope"] = " ".join(self._scopes)

        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._token_url,
                    data=form_data,
                    auth=httpx.BasicAuth(self._client_id, self._client_secret),
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise MCPAuthenticationError(
                "The MCP OAuth token request timed out."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise MCPAuthenticationError(
                "The MCP OAuth token request was rejected."
            ) from exc
        except httpx.HTTPError as exc:
            raise MCPAuthenticationError(
                "The MCP OAuth token request failed."
            ) from exc
        except ValueError as exc:
            raise MCPAuthenticationError(
                "The MCP OAuth token response was not valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise MCPAuthenticationError("The MCP OAuth token response was invalid.")

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise MCPAuthenticationError(
                "The MCP OAuth token response did not include an access token."
            )

        token_type = payload.get("token_type")
        normalized_type = _normalized_text(token_type) or "Bearer"
        expires_at = _expires_at_from_seconds(payload.get("expires_in"))

        return _CachedOAuthToken(
            access_token=access_token.strip(),
            token_type=normalized_type,
            expires_at=expires_at,
        )


def build_mcp_auth_provider(
    settings: MCPAuthSettings,
    *,
    timeout_seconds: int = 10,
    client_factory: HttpxAsyncClientFactory | None = None,
) -> MCPAuthProvider:
    """Build the auth provider configured for the active MCP endpoint."""

    if settings.mode == "none":
        return NoOpMCPAuthProvider()
    if settings.mode == "bearer":
        if settings.token is None:
            raise ToolingConfigurationError("Bearer MCP auth requires a configured token.")
        return StaticTokenMCPAuthProvider(settings.token)
    if settings.mode == "jwt":
        if settings.jwt is None:
            raise ToolingConfigurationError("JWT MCP auth requires a configured JWT.")
        return StaticTokenMCPAuthProvider(settings.jwt)
    if settings.mode == "oauth_client_credentials":
        if (
            settings.token_url is None
            or settings.client_id is None
            or settings.client_secret is None
        ):
            raise ToolingConfigurationError(
                "OAuth client-credentials MCP auth requires token URL, client ID, and client secret."
            )
        return OAuthClientCredentialsMCPAuthProvider(
            token_url=settings.token_url,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            scopes=settings.scopes,
            timeout_seconds=timeout_seconds,
            client_factory=client_factory,
        )

    raise ToolingConfigurationError("Unsupported MCP auth mode.")


def _token_is_fresh(token: _CachedOAuthToken) -> bool:
    if token.expires_at is None:
        return True
    refresh_at = token.expires_at - timedelta(seconds=_TOKEN_REFRESH_SKEW_SECONDS)
    return refresh_at > datetime.now(timezone.utc)


def _expires_at_from_seconds(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, float):
        seconds = int(value)
    elif isinstance(value, str):
        try:
            seconds = int(value.strip())
        except ValueError:
            return None
    else:
        return None

    if seconds <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _required_text(value: object, message: str) -> str:
    normalized = _normalized_text(value)
    if normalized is None:
        raise ToolingConfigurationError(message)
    return normalized


__all__ = [
    "HttpxAsyncClientFactory",
    "MCPAuthProvider",
    "NoOpMCPAuthProvider",
    "OAuthClientCredentialsMCPAuthProvider",
    "StaticTokenMCPAuthProvider",
    "build_mcp_auth_provider",
]