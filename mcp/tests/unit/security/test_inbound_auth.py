from __future__ import annotations

import pytest

from app.schemas import InboundAuthSettings, SecretsSettings
from app.security.auth import AuthError, create_auth_service
from app.security.secrets import EnvironmentSecretResolver


def _resolver(environ: dict[str, str] | None = None) -> EnvironmentSecretResolver:
    return EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["MCP_TOOL_", "WEBSEARCH_"]),
        environ=environ or {},
    )


def test_noop_auth_service_is_unauthenticated_without_request_context() -> None:
    service = create_auth_service(
        InboundAuthSettings(enabled=False, mode="none"),
        _resolver(),
    )

    context = service.current_request_context()

    assert service.build_auth_provider(base_url="http://localhost:9001") is None
    assert context.authenticated is False
    assert context.auth_subject is None
    assert context.auth_scopes == ()


def test_bearer_auth_service_requires_http_request_when_auth_is_enforced() -> None:
    service = create_auth_service(
        InboundAuthSettings(
            enabled=True,
            mode="bearer",
            bearer_token_env="MCP_BEARER_TOKEN",
        ),
        _resolver({"MCP_BEARER_TOKEN": "expected-token"}),
    )

    with pytest.raises(AuthError, match="Authentication required"):
        service.current_request_context(require_authenticated=True)


def test_bearer_auth_service_builds_transport_provider() -> None:
    service = create_auth_service(
        InboundAuthSettings(
            enabled=True,
            mode="bearer",
            bearer_token_env="MCP_BEARER_TOKEN",
        ),
        _resolver({"MCP_BEARER_TOKEN": "expected-token"}),
    )

    provider = service.build_auth_provider(base_url="http://localhost:9001")

    assert provider is not None
    assert service.enabled is True
    assert service.mode_name == "bearer"