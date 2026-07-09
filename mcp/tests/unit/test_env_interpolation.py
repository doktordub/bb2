from app.config import resolve_env_placeholders
from app.errors import MCPConfigurationError


def test_required_env_placeholder_uses_value(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TEST_VALUE", "resolved")

    resolved = resolve_env_placeholders({"key": "${env:MCP_TEST_VALUE}"})

    assert resolved == {"key": "resolved"}


def test_default_env_placeholder_uses_default_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("MCP_TEST_VALUE", raising=False)

    resolved = resolve_env_placeholders(["${env:MCP_TEST_VALUE:fallback}"])

    assert resolved == ["fallback"]


def test_required_env_placeholder_fails_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("MCP_REQUIRED_VALUE", raising=False)

    try:
        resolve_env_placeholders("${env:MCP_REQUIRED_VALUE}")
    except MCPConfigurationError as exc:
        assert "MCP_REQUIRED_VALUE" in str(exc)
    else:
        raise AssertionError("Expected MCPConfigurationError for a missing required env var.")


def test_malformed_env_placeholder_fails_fast() -> None:
    try:
        resolve_env_placeholders("${env:MCP_BROKEN")
    except MCPConfigurationError as exc:
        assert "Malformed environment placeholder" in str(exc)
    else:
        raise AssertionError("Expected MCPConfigurationError for a malformed placeholder.")