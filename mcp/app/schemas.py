"""Typed configuration models for the MCP server."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TransportName = Literal["stdio", "http", "sse", "streamable-http"]
InboundAuthMode = Literal["none", "bearer", "jwt"]
OutboundAuthMode = Literal["none", "oauth"]
TLSMode = Literal["off", "terminate_here", "terminate_upstream"]
SecretsProvider = Literal["env", "file", "future_vault"]

DEFAULT_ALLOWED_TOOL_ENV_PREFIXES = ["MCP_TOOL_", "WEBSEARCH_"]
VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "development", "test"})


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class StrictSettingsModel(BaseModel):
    """Base model for strict configuration validation."""

    model_config = ConfigDict(extra="forbid")


class ServerSettings(StrictSettingsModel):
    name: str
    version: str
    environment: str
    host: str
    port: int
    path: str
    transport: TransportName
    public_base_url: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("server.path must start with '/'.")
        return value


class RuntimeSettings(StrictSettingsModel):
    tools_dir: str
    discovery_on_startup: bool
    fail_on_required_tool_error: bool
    fail_on_optional_tool_error: bool
    reload_tools_in_dev: bool = False


class JWTSettings(StrictSettingsModel):
    issuer: str | None = None
    audience: str | None = None
    jwks_url: str | None = None
    allowed_algorithms: tuple[str, ...] = Field(default=("RS256",))

    @field_validator("issuer", "audience", "jwks_url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("allowed_algorithms", mode="before")
    @classmethod
    def validate_allowed_algorithms(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ("RS256",)
        if isinstance(value, str):
            value = [value]

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = str(item).strip().upper()
            if not normalized:
                continue
            if normalized not in seen:
                cleaned.append(normalized)
                seen.add(normalized)

        if not cleaned:
            raise ValueError("security.inbound_auth.jwt.allowed_algorithms must not be empty.")
        return tuple(cleaned)


class InboundAuthSettings(StrictSettingsModel):
    enabled: bool
    mode: InboundAuthMode
    bearer_token_env: str | None = None
    jwt: JWTSettings = Field(default_factory=JWTSettings)

    @field_validator("bearer_token_env", mode="before")
    @classmethod
    def normalize_bearer_token_env(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class OAuthClientSettings(StrictSettingsModel):
    token_url: str
    client_id_env: str
    client_secret_env: str
    scopes: tuple[str, ...] = Field(default=())
    audience: str | None = None
    extra_params: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "token_url",
        "client_id_env",
        "client_secret_env",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: Any) -> str:
        normalized = _normalize_optional_text(None if value is None else str(value))
        if normalized is None:
            raise ValueError("OAuth client credential fields must not be blank.")
        return normalized

    @field_validator("audience", mode="before")
    @classmethod
    def normalize_audience(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("scopes", mode="before")
    @classmethod
    def validate_scopes(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = [value]

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = str(item).strip()
            if not normalized or normalized in seen:
                continue
            cleaned.append(normalized)
            seen.add(normalized)
        return tuple(cleaned)


class OutboundAuthSettings(StrictSettingsModel):
    default_mode: OutboundAuthMode
    oauth_clients: dict[str, OAuthClientSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_default_mode(self) -> "OutboundAuthSettings":
        if self.default_mode == "oauth" and not self.oauth_clients:
            raise ValueError(
                "security.outbound_auth.default_mode='oauth' requires at least one oauth client."
            )
        return self


class TLSSettings(StrictSettingsModel):
    mode: TLSMode
    cert_file: str | None = None
    key_file: str | None = None
    behind_proxy: bool

    @field_validator("cert_file", "key_file", mode="before")
    @classmethod
    def normalize_tls_file_path(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_tls_files(self) -> "TLSSettings":
        if self.mode == "terminate_here" and (not self.cert_file or not self.key_file):
            raise ValueError(
                "security.tls.mode='terminate_here' requires both cert_file and key_file."
            )
        return self


class SecretsSettings(StrictSettingsModel):
    provider: SecretsProvider
    allow_tool_env_prefixes: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_TOOL_ENV_PREFIXES)
    )

    @field_validator("allow_tool_env_prefixes")
    @classmethod
    def validate_prefixes(cls, values: list[str]) -> list[str]:
        cleaned = [value for value in values if value]
        if not cleaned:
            raise ValueError("security.secrets.allow_tool_env_prefixes must not be empty.")
        return cleaned


class SecuritySettings(StrictSettingsModel):
    inbound_auth: InboundAuthSettings
    outbound_auth: OutboundAuthSettings
    tls: TLSSettings
    secrets: SecretsSettings


class PolicySettings(StrictSettingsModel):
    default_tool_enabled: bool = False
    expose_internal_tools: bool = True
    expose_health_tool: bool = True
    expose_capabilities_tool: bool = True
    require_tool_manifest: bool = True
    require_tool_config_validation: bool = True
    reject_secret_like_arguments: bool = True


class ObservabilitySettings(StrictSettingsModel):
    log_level: str
    json_logs: bool
    trace_headers: dict[str, str] = Field(default_factory=dict)
    redact_secrets: bool
    metrics_enabled: bool = False
    max_log_payload_chars: int

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in VALID_LOG_LEVELS:
            raise ValueError(f"Unsupported log level: {value!r}")
        return normalized


class RateLimitSettings(StrictSettingsModel):
    enabled: bool
    per_tool_per_minute: int = Field(ge=1)


class DefaultsSettings(StrictSettingsModel):
    timeout_seconds: int = Field(ge=1)
    max_result_bytes: int = Field(ge=1)
    max_argument_bytes: int = Field(ge=1)
    max_results: int = Field(ge=1)
    rate_limit: RateLimitSettings


class ToolEnablementSettings(StrictSettingsModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    required: bool = False
    config_file: str | None = None

    def runtime_config(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class AppSettings(StrictSettingsModel):
    server: ServerSettings
    runtime: RuntimeSettings
    security: SecuritySettings
    policy: PolicySettings
    observability: ObservabilitySettings
    defaults: DefaultsSettings
    tools: dict[str, ToolEnablementSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "AppSettings":
        inbound_auth = self.security.inbound_auth
        environment = self.server.environment.strip().lower()

        if not inbound_auth.enabled and inbound_auth.mode != "none":
            raise ValueError(
                "security.inbound_auth.mode must be 'none' when inbound auth is disabled."
            )

        if inbound_auth.mode == "none":
            if inbound_auth.enabled and environment not in LOCAL_ENVIRONMENTS:
                raise ValueError(
                    "security.inbound_auth.mode='none' is only allowed outside local/test environments when inbound auth is disabled."
                )
            return self

        if not inbound_auth.enabled:
            raise ValueError(
                "security.inbound_auth.enabled must be true when inbound auth mode is bearer or jwt."
            )

        if inbound_auth.mode == "bearer" and not inbound_auth.bearer_token_env:
            raise ValueError(
                "security.inbound_auth.bearer_token_env is required for bearer authentication."
            )

        if inbound_auth.mode == "jwt":
            jwt = inbound_auth.jwt
            missing_fields = [
                field_name
                for field_name, value in {
                    "issuer": jwt.issuer,
                    "audience": jwt.audience,
                    "jwks_url": jwt.jwks_url,
                }.items()
                if not value
            ]
            if missing_fields:
                raise ValueError(
                    "security.inbound_auth.jwt is missing required fields: "
                    + ", ".join(missing_fields)
                )

        return self