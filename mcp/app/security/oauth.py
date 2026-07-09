"""Outbound OAuth client-credentials support for MCP plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.context import OutboundAuthService
from app.errors import MCPOAuthError
from app.observability.logging import StructuredLogger
from app.schemas import OAuthClientSettings, OutboundAuthSettings
from app.security.secrets import EnvironmentSecretResolver
from app.services.clock import Clock
from app.services.http_client import HttpClientFactory


@dataclass(frozen=True, slots=True)
class CachedAccessToken:
    """Cached outbound access token with a bounded expiry timestamp."""

    token: str
    expires_at_epoch_seconds: int


@dataclass(slots=True)
class NoopOutboundAuthService(OutboundAuthService):
    """Disabled outbound auth service."""

    mode_name: str = "none"
    configured_clients: int = 0

    async def get_access_token(self, client_name: str) -> str:
        raise MCPOAuthError(
            f"Outbound OAuth client {client_name!r} is not configured for this MCP server."
        )


@dataclass(slots=True)
class OAuthClientCredentialsProvider(OutboundAuthService):
    """Logical-client OAuth access token provider with simple in-memory caching."""

    settings: OutboundAuthSettings
    secret_resolver: EnvironmentSecretResolver
    http_client_factory: HttpClientFactory
    clock: Clock
    logger: StructuredLogger
    _cache: dict[str, CachedAccessToken] = field(default_factory=dict, init=False, repr=False)

    @property
    def mode_name(self) -> str:
        return "oauth"

    @property
    def configured_clients(self) -> int:
        return len(self.settings.oauth_clients)

    async def get_access_token(self, client_name: str) -> str:
        client_settings = self.settings.oauth_clients.get(client_name)
        if client_settings is None:
            raise MCPOAuthError(f"Unknown outbound OAuth client {client_name!r}.")

        cached = self._cache.get(client_name)
        now_epoch = int(self.clock.now().timestamp())
        if cached is not None and cached.expires_at_epoch_seconds - now_epoch > 30:
            return cached.token

        token = await self._request_access_token(client_name, client_settings)
        return token

    async def _request_access_token(
        self,
        client_name: str,
        client_settings: OAuthClientSettings,
    ) -> str:
        client_id = self.secret_resolver.get(
            f"{client_name}_client_id",
            env_var=client_settings.client_id_env,
            required=True,
        )
        client_secret = self.secret_resolver.get(
            f"{client_name}_client_secret",
            env_var=client_settings.client_secret_env,
            required=True,
        )
        assert client_id is not None
        assert client_secret is not None

        form_data = {
            "grant_type": "client_credentials",
            "client_id": client_id.get_secret_value(),
            "client_secret": client_secret.get_secret_value(),
        }
        if client_settings.scopes:
            form_data["scope"] = " ".join(client_settings.scopes)
        if client_settings.audience:
            form_data["audience"] = client_settings.audience
        form_data.update(client_settings.extra_params)

        async with self.http_client_factory.create_client(
            headers={"Accept": "application/json"}
        ) as client:
            response = await client.post(client_settings.token_url, data=form_data)

        if response.status_code >= 400:
            raise MCPOAuthError(
                f"Failed to retrieve an outbound access token for {client_name!r}."
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise MCPOAuthError(
                f"OAuth token response for {client_name!r} was not valid JSON."
            ) from error

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise MCPOAuthError(
                f"OAuth token response for {client_name!r} did not include an access token."
            )

        expires_in = payload.get("expires_in", 300)
        try:
            expires_in_seconds = max(60, int(expires_in))
        except (TypeError, ValueError):
            expires_in_seconds = 300

        expires_at_epoch_seconds = int(
            (self.clock.now() + timedelta(seconds=expires_in_seconds)).timestamp()
        )
        self._cache[client_name] = CachedAccessToken(
            token=access_token,
            expires_at_epoch_seconds=expires_at_epoch_seconds,
        )
        self.logger.info(
            "mcp.security.oauth.token_acquired",
            payload={
                "client_name": client_name,
                "expires_in": expires_in_seconds,
            },
        )
        return access_token


def create_outbound_auth_service(
    settings: OutboundAuthSettings,
    secret_resolver: EnvironmentSecretResolver,
    http_client_factory: HttpClientFactory,
    clock: Clock,
    logger: StructuredLogger,
) -> OutboundAuthService:
    """Create the shared outbound auth service for tool runtime contexts."""

    if not settings.oauth_clients:
        return NoopOutboundAuthService(mode_name=settings.default_mode, configured_clients=0)

    return OAuthClientCredentialsProvider(
        settings=settings,
        secret_resolver=secret_resolver,
        http_client_factory=http_client_factory,
        clock=clock,
        logger=logger,
    )