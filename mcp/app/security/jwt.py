"""JWT validation isolated behind the MCP security boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.errors import MCPJWTValidationError
from app.schemas import JWTSettings
from app.security.scopes import extract_scopes


def _import_pyjwt() -> tuple[Any, Any]:
    try:
        import jwt
        from jwt import PyJWKClient
    except ModuleNotFoundError as error:  # pragma: no cover - exercised in integration env
        raise MCPJWTValidationError(
            "JWT authentication requires the PyJWT package with cryptography support."
        ) from error
    return jwt, PyJWKClient


def _normalize_claim(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class VerifiedJWTIdentity:
    """Safe JWT identity data exposed to higher-level auth services."""

    subject: str
    caller_service: str | None
    scopes: tuple[str, ...]


@dataclass(slots=True)
class JWTVerifierService:
    """Validates JWT bearer tokens against a configured JWKS endpoint."""

    settings: JWTSettings
    _jwt: Any = field(init=False, repr=False)
    _jwk_client: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.settings.issuer or not self.settings.audience or not self.settings.jwks_url:
            raise MCPJWTValidationError(
                "JWT verification requires issuer, audience, and jwks_url configuration."
            )

        jwt_module, jwk_client_type = _import_pyjwt()
        self._jwt = jwt_module
        self._jwk_client = jwk_client_type(self.settings.jwks_url)

    def verify_token(self, token: str) -> VerifiedJWTIdentity:
        """Validate JWT signature and required claims."""

        try:
            header = self._jwt.get_unverified_header(token)
            algorithm = str(header.get("alg", "")).strip().upper()
            if algorithm not in self.settings.allowed_algorithms:
                raise MCPJWTValidationError("JWT authentication failed.")

            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = self._jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.settings.allowed_algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except MCPJWTValidationError:
            raise
        except Exception as error:
            raise MCPJWTValidationError("JWT authentication failed.") from error

        subject = (
            _normalize_claim(claims.get("sub"))
            or _normalize_claim(claims.get("client_id"))
            or _normalize_claim(claims.get("azp"))
        )
        if subject is None:
            raise MCPJWTValidationError("JWT authentication failed.")

        caller_service = (
            _normalize_claim(claims.get("azp"))
            or _normalize_claim(claims.get("client_id"))
            or _normalize_claim(claims.get("client_name"))
        )
        return VerifiedJWTIdentity(
            subject=subject,
            caller_service=caller_service,
            scopes=extract_scopes(claims),
        )