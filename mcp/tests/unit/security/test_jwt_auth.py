from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.tests import run_server_async
import jwt
from jwt.algorithms import RSAAlgorithm
import pytest
import yaml

from app.bootstrap import bootstrap
from app.errors import MCPJWTValidationError
from app.schemas import JWTSettings
from app.security.jwt import JWTVerifierService


TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
JWT_ISSUER = "https://issuer.example"
JWT_AUDIENCE = "mcp-backend"


def _build_signing_material() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"
    return private_key, public_jwk


def _mint_token(private_key: object, *, audience: str = JWT_AUDIENCE) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": JWT_ISSUER,
            "aud": audience,
            "sub": "backend-service",
            "azp": "backend",
            "scope": "tools:use web:search",
            "exp": now + 3600,
            "iat": now,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


class _JWKSHandler(BaseHTTPRequestHandler):
    jwks: dict[str, object] = {"keys": []}

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/jwks":
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps(self.jwks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        del format, args


class _JWKSFixture:
    def __init__(self, jwks: dict[str, object]) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _JWKSHandler)
        _JWKSHandler.jwks = jwks
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}/jwks"

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def _write_jwt_config(tmp_path: Path, *, jwks_url: str) -> Path:
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
                        "mode": "jwt",
                        "jwt": {
                            "issuer": JWT_ISSUER,
                            "audience": JWT_AUDIENCE,
                            "jwks_url": jwks_url,
                            "allowed_algorithms": ["RS256"],
                        },
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


def test_jwt_verifier_validates_rs256_tokens() -> None:
    private_key, public_jwk = _build_signing_material()
    token = _mint_token(private_key)

    with _JWKSFixture({"keys": [public_jwk]}) as jwks_url:
        verifier = JWTVerifierService(
            JWTSettings(
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                jwks_url=jwks_url,
                allowed_algorithms=("RS256",),
            )
        )
        identity = verifier.verify_token(token)

    assert identity.subject == "backend-service"
    assert identity.caller_service == "backend"
    assert identity.scopes == ("tools:use", "web:search")


def test_jwt_verifier_rejects_wrong_audience() -> None:
    private_key, public_jwk = _build_signing_material()
    token = _mint_token(private_key, audience="wrong-audience")

    with _JWKSFixture({"keys": [public_jwk]}) as jwks_url:
        verifier = JWTVerifierService(
            JWTSettings(
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                jwks_url=jwks_url,
                allowed_algorithms=("RS256",),
            )
        )

        with pytest.raises(MCPJWTValidationError, match="JWT authentication failed"):
            verifier.verify_token(token)


@pytest.mark.asyncio
async def test_jwt_auth_allows_authenticated_http_calls(tmp_path: Path) -> None:
    private_key, public_jwk = _build_signing_material()
    token = _mint_token(private_key)

    with _JWKSFixture({"keys": [public_jwk]}) as jwks_url:
        runtime = bootstrap(_write_jwt_config(tmp_path, jwks_url=jwks_url))

        async with run_server_async(runtime.server) as url:
            async with Client(StreamableHttpTransport(url, auth=token)) as client:
                result = await client.call_tool("example.echo", {"message": "hello"})

    assert result.structured_content is not None
    assert result.structured_content["ok"] is True
    assert result.structured_content["data"]["message"] == "example: hello"