from __future__ import annotations

import httpx
import pytest

from app.config.view import MCPAuthSettings
from app.tools.errors import MCPAuthenticationError
from app.tools.mcp import (
    NoOpMCPAuthProvider,
    OAuthClientCredentialsMCPAuthProvider,
    StaticTokenMCPAuthProvider,
    build_mcp_auth_provider,
)


async def test_noop_auth_provider_returns_no_headers() -> None:
    provider = NoOpMCPAuthProvider()

    headers = await provider.get_headers()

    assert headers == {}


async def test_static_token_auth_provider_builds_authorization_header() -> None:
    provider = StaticTokenMCPAuthProvider("token-123")

    headers = await provider.get_headers()

    assert headers == {"Authorization": "Bearer token-123"}


async def test_build_auth_provider_supports_bearer_and_jwt_modes() -> None:
    bearer = build_mcp_auth_provider(
        MCPAuthSettings(
            mode="bearer",
            token="bearer-token",
            jwt=None,
            token_url=None,
            client_id=None,
            client_secret=None,
            scopes=(),
        )
    )
    jwt = build_mcp_auth_provider(
        MCPAuthSettings(
            mode="jwt",
            token=None,
            jwt="jwt-token",
            token_url=None,
            client_id=None,
            client_secret=None,
            scopes=(),
        )
    )

    assert await bearer.get_headers() == {"Authorization": "Bearer bearer-token"}
    assert await jwt.get_headers() == {"Authorization": "Bearer jwt-token"}


async def test_oauth_auth_provider_fetches_and_caches_access_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "oauth-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    provider = OAuthClientCredentialsMCPAuthProvider(
        token_url="https://auth.example.local/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=("tools.read", "tools.execute"),
        client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )

    headers_one = await provider.get_headers()
    headers_two = await provider.get_headers()

    assert headers_one == {"Authorization": "Bearer oauth-token"}
    assert headers_two == {"Authorization": "Bearer oauth-token"}
    assert len(requests) == 1
    assert requests[0].url == httpx.URL("https://auth.example.local/token")
    assert requests[0].content == b"grant_type=client_credentials&scope=tools.read+tools.execute"


async def test_oauth_auth_provider_raises_safe_error_without_leaking_secrets() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "error_description": "secret=super-secret",
            },
        )

    provider = OAuthClientCredentialsMCPAuthProvider(
        token_url="https://auth.example.local/token",
        client_id="client-id",
        client_secret="super-secret",
        client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )

    with pytest.raises(MCPAuthenticationError) as exc_info:
        await provider.get_headers()

    assert "super-secret" not in str(exc_info.value)