import pytest
from pydantic import SecretStr

from app.errors import MCPSecretError
from app.schemas import SecretsSettings
from app.security.secrets import EnvironmentSecretResolver


def test_secret_resolver_reads_allowed_environment_secret(monkeypatch) -> None:
    monkeypatch.setenv("WEBSEARCH_API_KEY", "super-secret")
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={"WEBSEARCH_API_KEY": "super-secret"},
    ).for_tools()

    value = resolver.get("websearch_api_key", env_var="WEBSEARCH_API_KEY")

    assert value == SecretStr("super-secret")
    assert value is not None
    assert value.get_secret_value() == "super-secret"


def test_secret_resolver_fails_for_missing_required_secret() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={},
    ).for_tools()

    with pytest.raises(MCPSecretError):
        resolver.get("websearch_api_key", env_var="WEBSEARCH_API_KEY")


def test_secret_resolver_rejects_disallowed_environment_variable() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={"UNSAFE_KEY": "value"},
    ).for_tools()

    with pytest.raises(MCPSecretError):
        resolver.get("websearch_api_key", env_var="UNSAFE_KEY")


def test_service_secret_resolver_can_read_non_tool_secret_names() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={"MCP_BEARER_TOKEN": "server-secret"},
    )

    value = resolver.get("inbound_auth_token", env_var="MCP_BEARER_TOKEN")

    assert value is not None
    assert value.get_secret_value() == "server-secret"


def test_optional_secret_lookup_returns_none() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={},
    ).for_tools()

    assert resolver.get("websearch_api_key", env_var="WEBSEARCH_API_KEY", required=False) is None


def test_secret_repr_is_redacted() -> None:
    resolver = EnvironmentSecretResolver(
        settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["WEBSEARCH_"]),
        environ={"WEBSEARCH_API_KEY": "super-secret"},
    ).for_tools()

    value = resolver.get("websearch_api_key", env_var="WEBSEARCH_API_KEY")

    assert value is not None
    assert "super-secret" not in repr(value)