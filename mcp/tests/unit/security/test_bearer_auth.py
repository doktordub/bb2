from __future__ import annotations

from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.tests import run_server_async
import pytest
import yaml

from app.bootstrap import bootstrap
from app.schemas import InboundAuthSettings, SecretsSettings
from app.security.auth import AuthError, BearerAuthVerifier
from app.security.secrets import EnvironmentSecretResolver


TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"


def _write_bearer_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {
                    "name": "main_mcp",
                    "version": "1.0.0",
                    "environment": "test",
                    "host": "127.0.0.1",
                    "port": 9001,
                    "path": "/mcp",
                    "transport": "http",
                    "public_base_url": "http://127.0.0.1:9001",
                },
                "runtime": {
                    "tools_dir": TOOLS_DIR.as_posix(),
                    "discovery_on_startup": True,
                    "fail_on_required_tool_error": True,
                    "fail_on_optional_tool_error": False,
                },
                "security": {
                    "inbound_auth": {
                        "enabled": True,
                        "mode": "bearer",
                        "bearer_token_env": "MCP_BEARER_TOKEN",
                    },
                    "outbound_auth": {"default_mode": "none", "oauth_clients": {}},
                    "tls": {"mode": "terminate_upstream", "behind_proxy": True},
                    "secrets": {
                        "provider": "env",
                        "allow_tool_env_prefixes": ["MCP_TOOL_", "WEBSEARCH_"],
                    },
                },
                "policy": {
                    "default_tool_enabled": False,
                    "expose_internal_tools": True,
                    "expose_health_tool": True,
                    "expose_capabilities_tool": True,
                    "require_tool_manifest": True,
                    "require_tool_config_validation": True,
                    "reject_secret_like_arguments": True,
                },
                "observability": {
                    "log_level": "INFO",
                    "json_logs": True,
                    "trace_headers": {},
                    "redact_secrets": True,
                    "metrics_enabled": False,
                    "max_log_payload_chars": 2000,
                },
                "defaults": {
                    "timeout_seconds": 30,
                    "max_result_bytes": 262144,
                    "max_argument_bytes": 65536,
                    "max_results": 10,
                    "rate_limit": {
                        "enabled": True,
                        "per_tool_per_minute": 60,
                    },
                },
                "tools": {
                    "example_tool": {
                        "enabled": True,
                        "required": True,
                        "config_file": "config.yaml",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def test_bearer_verifier_uses_constant_time_comparison() -> None:
    verifier = BearerAuthVerifier(
        settings=InboundAuthSettings(
            enabled=True,
            mode="bearer",
            bearer_token_env="MCP_BEARER_TOKEN",
        ),
        secret_resolver=EnvironmentSecretResolver(
            settings=SecretsSettings(provider="env", allow_tool_env_prefixes=["MCP_TOOL_", "WEBSEARCH_"]),
            environ={"MCP_BEARER_TOKEN": "expected-token"},
        ),
    )

    context = verifier.verify_token(
        "expected-token",
        headers={
            "x-trace-id": "trace-123",
            "x-request-id": "request-456",
            "x-caller-service": "backend",
        },
    )

    assert context.authenticated is True
    assert context.trace_id == "trace-123"
    assert context.request_id == "request-456"
    assert context.caller_service == "backend"
    assert context.auth_subject == "backend"

    with pytest.raises(AuthError, match="Authentication failed"):
        verifier.verify_token("wrong-token")


@pytest.mark.asyncio
async def test_bearer_auth_allows_authenticated_http_calls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MCP_BEARER_TOKEN", "expected-token")
    runtime = bootstrap(_write_bearer_config(tmp_path))

    async with run_server_async(runtime.server) as url:
        async with Client(StreamableHttpTransport(url, auth="expected-token")) as client:
            result = await client.call_tool("example.echo", {"message": "hello"})

    assert result.structured_content is not None
    assert result.structured_content["ok"] is True
    assert result.structured_content["data"]["message"] == "example: hello"


@pytest.mark.asyncio
async def test_bearer_auth_rejects_missing_http_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MCP_BEARER_TOKEN", "expected-token")
    runtime = bootstrap(_write_bearer_config(tmp_path))

    async with run_server_async(runtime.server) as url:
        with pytest.raises(Exception, match="401|Authentication|Unauthorized"):
            async with Client(StreamableHttpTransport(url)) as client:
                await client.call_tool("example.echo", {"message": "hello"})