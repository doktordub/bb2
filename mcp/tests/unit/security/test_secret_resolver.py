from __future__ import annotations

import pytest

from app.errors import MCPSecretError
from app.schemas import SecretsSettings
from app.security.secrets import EnvironmentSecretResolver


def test_tool_secret_resolver_enforces_allowed_prefixes() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={"WEBSEARCH_API_KEY": "secret-value"},
    ).for_tools()

    value = resolver.get("websearch_api_key", env_var="WEBSEARCH_API_KEY")

    assert value is not None
    assert value.get_secret_value() == "secret-value"

    with pytest.raises(MCPSecretError):
        resolver.get("websearch_api_key", env_var="MCP_BEARER_TOKEN")


def test_service_secret_resolver_keeps_repr_redacted() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={"MCP_BEARER_TOKEN": "very-secret-token"},
    )

    value = resolver.get("mcp_bearer_token", env_var="MCP_BEARER_TOKEN")

    assert value is not None
    assert "very-secret-token" not in repr(value)