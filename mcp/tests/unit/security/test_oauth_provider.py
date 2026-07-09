from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.observability.logging import create_bootstrap_logger
from app.schemas import OAuthClientSettings, OutboundAuthSettings, SecretsSettings
from app.security.oauth import OAuthClientCredentialsProvider, create_outbound_auth_service
from app.security.secrets import EnvironmentSecretResolver


class FrozenClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class FakeHttpClientFactory:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    @asynccontextmanager
    async def create_client(self, **kwargs):  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "oauth-access-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers=kwargs.get("headers"),
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_oauth_provider_caches_token_by_client_name() -> None:
    clock = FrozenClock()
    factory = FakeHttpClientFactory()
    provider = OAuthClientCredentialsProvider(
        settings=OutboundAuthSettings(
            default_mode="oauth",
            oauth_clients={
                "example_api": OAuthClientSettings(
                    token_url="https://example.test/oauth/token",
                    client_id_env="EXAMPLE_CLIENT_ID",
                    client_secret_env="EXAMPLE_CLIENT_SECRET",
                    scopes=("search.read",),
                )
            },
        ),
        secret_resolver=EnvironmentSecretResolver(
            settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["MCP_TOOL_", "WEBSEARCH_"]),
            environ={
                "EXAMPLE_CLIENT_ID": "client-id",
                "EXAMPLE_CLIENT_SECRET": "client-secret",
            },
        ),
        http_client_factory=factory,  # type: ignore[arg-type]
        clock=clock,
        logger=create_bootstrap_logger(),
    )

    first = await provider.get_access_token("example_api")
    second = await provider.get_access_token("example_api")

    assert first == "oauth-access-token"
    assert second == "oauth-access-token"
    assert len(factory.calls) == 1
    assert b"grant_type=client_credentials" in factory.calls[0].content
    assert b"scope=search.read" in factory.calls[0].content


def test_create_outbound_auth_service_returns_noop_when_no_clients_are_configured() -> None:
    service = create_outbound_auth_service(
        settings=OutboundAuthSettings(default_mode="none", oauth_clients={}),
        secret_resolver=EnvironmentSecretResolver(
            settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["MCP_TOOL_", "WEBSEARCH_"]),
            environ={},
        ),
        http_client_factory=FakeHttpClientFactory(),  # type: ignore[arg-type]
        clock=FrozenClock(),
        logger=create_bootstrap_logger(),
    )

    assert service.mode_name == "none"
    assert service.configured_clients == 0