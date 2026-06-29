"""Backend settings with deterministic backend-root-relative env loading."""

from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = BACKEND_ROOT / ".env"
DEFAULT_APP_CONFIG_PATH = "config/app.yaml"
DEFAULT_APP_CONFIG_OVERRIDE_PATH = "config/app.local.yaml"
DEFAULT_APP_DATA_DIR = "data"
DEFAULT_APP_LOG_DIR = "logs"
DEFAULT_APP_RUNTIME_DIR = "runtime"


def _alias_choices(*names: str) -> AliasChoices:
    return AliasChoices(*names)


def _load_env_file_values(env_file: str | Path | None) -> dict[str, str]:
    if env_file is None:
        return {}

    env_path = Path(env_file)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def _effective_env(env_file: str | Path | None) -> dict[str, str]:
    import os

    env = _load_env_file_values(env_file)
    env.update(os.environ)
    return env


def _resolve_env_file_setting(
    env_file: str | Path | Sequence[str | Path] | None,
) -> str | Path | None:
    if isinstance(env_file, (str, Path)) or env_file is None:
        return env_file
    if isinstance(env_file, Sequence):
        for candidate in env_file:
            if isinstance(candidate, (str, Path)):
                return candidate
    return None


def _normalize_path_setting(value: object, *, default: str) -> str:
    if value is None:
        return default

    if isinstance(value, Path):
        return value.as_posix()

    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else default

    return str(value)


def _resolve_backend_relative_path(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate
    return candidate.resolve(strict=False)


class Settings(BaseSettings):
    """Foundation settings for backend startup and tests."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "pluggable-agentic-ai-backend"
    app_version: str = "0.1.0"
    app_env: str = Field(default="local", validation_alias="APP_ENV")
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")

    host: str = Field(
        default="127.0.0.1",
        validation_alias=_alias_choices("BACKEND_HOST", "APP_HOST"),
    )
    port: int = Field(
        default=8000,
        validation_alias=_alias_choices("BACKEND_PORT", "APP_PORT"),
    )
    reload: bool = Field(
        default=False,
        validation_alias=_alias_choices("BACKEND_RELOAD", "APP_RELOAD"),
    )

    app_usecase: str | None = Field(default=None, validation_alias="APP_USECASE")
    app_config_path: str = Field(
        default=DEFAULT_APP_CONFIG_PATH,
        validation_alias="APP_CONFIG_PATH",
    )
    app_config_override_path: str = Field(
        default=DEFAULT_APP_CONFIG_OVERRIDE_PATH,
        validation_alias="APP_CONFIG_OVERRIDE_PATH",
    )
    app_data_dir: str = Field(default=DEFAULT_APP_DATA_DIR, validation_alias="APP_DATA_DIR")
    app_log_dir: str = Field(default=DEFAULT_APP_LOG_DIR, validation_alias="APP_LOG_DIR")
    app_runtime_dir: str = Field(default=DEFAULT_APP_RUNTIME_DIR, validation_alias="APP_RUNTIME_DIR")
    app_config_strict: bool = Field(default=False, validation_alias="APP_CONFIG_STRICT")
    app_public_base_url: str | None = Field(default=None, validation_alias="APP_PUBLIC_BASE_URL")
    app_graceful_shutdown_seconds: int = Field(
        default=20,
        validation_alias="APP_GRACEFUL_SHUTDOWN_SECONDS",
    )
    metrics_enabled: bool = Field(default=True, validation_alias="METRICS_ENABLED")
    metrics_bind_host: str = Field(default="127.0.0.1", validation_alias="METRICS_BIND_HOST")
    metrics_port: int = Field(default=9102, validation_alias="METRICS_PORT")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_json: bool = Field(
        default=True,
        validation_alias=_alias_choices("LOG_JSON", "LOG_FORMAT"),
    )

    docs_url: str | None = "/docs"
    redoc_url: str | None = "/redoc"

    mcp_main_url: str | None = Field(default=None, validation_alias="MCP_MAIN_URL")
    mcp_auth_mode: str | None = Field(default=None, validation_alias="MCP_AUTH_MODE")
    mcp_bearer_token: str | None = Field(
        default=None,
        validation_alias="MCP_BEARER_TOKEN",
    )
    mcp_jwt: str | None = Field(default=None, validation_alias="MCP_JWT")
    mcp_oauth_token_url: str | None = Field(
        default=None,
        validation_alias="MCP_OAUTH_TOKEN_URL",
    )
    mcp_oauth_client_id: str | None = Field(
        default=None,
        validation_alias="MCP_OAUTH_CLIENT_ID",
    )
    mcp_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias="MCP_OAUTH_CLIENT_SECRET",
    )
    llm_local_qwen_base_url: str | None = Field(
        default=None,
        validation_alias=_alias_choices("LLM_LOCAL_QWEN_BASE_URL", "LOCAL_LLM_BASE_URL"),
    )
    llm_local_qwen_api_key: str | None = Field(
        default=None,
        validation_alias=_alias_choices("LLM_LOCAL_QWEN_API_KEY", "LOCAL_LLM_API_KEY"),
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    memory_store_config: str | None = Field(
        default=None,
        validation_alias=_alias_choices("MEMORY_STORE_CONFIG", "MEMORY_STORE_CONFIG_PATH"),
    )
    sqlite_workflow_state_url: str | None = Field(
        default=None,
        validation_alias="SQLITE_WORKFLOW_STATE_URL",
    )
    sqlite_trace_url: str | None = Field(default=None, validation_alias="SQLITE_TRACE_URL")

    @field_validator("app_config_path", mode="before")
    @classmethod
    def normalize_app_config_path(cls, value: object) -> str:
        return _normalize_path_setting(value, default=DEFAULT_APP_CONFIG_PATH)

    @field_validator("app_config_override_path", mode="before")
    @classmethod
    def normalize_app_config_override_path(cls, value: object) -> str:
        return _normalize_path_setting(value, default=DEFAULT_APP_CONFIG_OVERRIDE_PATH)

    @field_validator("app_data_dir", mode="before")
    @classmethod
    def normalize_app_data_dir(cls, value: object) -> str:
        return _normalize_path_setting(value, default=DEFAULT_APP_DATA_DIR)

    @field_validator("app_log_dir", mode="before")
    @classmethod
    def normalize_app_log_dir(cls, value: object) -> str:
        return _normalize_path_setting(value, default=DEFAULT_APP_LOG_DIR)

    @field_validator("app_runtime_dir", mode="before")
    @classmethod
    def normalize_app_runtime_dir(cls, value: object) -> str:
        return _normalize_path_setting(value, default=DEFAULT_APP_RUNTIME_DIR)

    @field_validator("log_json", mode="before")
    @classmethod
    def normalize_log_json(cls, value: object) -> bool | object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "json":
                return True
            if normalized in {"text", "plain", "console"}:
                return False
        return value

    @property
    def resolved_app_config_path(self) -> Path:
        return _resolve_backend_relative_path(self.app_config_path)

    @property
    def resolved_app_config_override_path(self) -> Path:
        return _resolve_backend_relative_path(self.app_config_override_path)

    @property
    def resolved_app_data_dir(self) -> Path:
        return _resolve_backend_relative_path(self.app_data_dir)

    @property
    def resolved_app_log_dir(self) -> Path:
        return _resolve_backend_relative_path(self.app_log_dir)

    @property
    def resolved_app_runtime_dir(self) -> Path:
        return _resolve_backend_relative_path(self.app_runtime_dir)

    def environment_overrides(self) -> dict[str, str]:
        env = _effective_env(_resolve_env_file_setting(self.model_config.get("env_file")))

        def _set_if_present(target: str, aliases: Iterable[str]) -> None:
            for alias in aliases:
                value = env.get(alias)
                if value is None or value == "":
                    continue
                env[target] = value
                break

        _set_if_present("APP_ENV", ("APP_ENV",))
        _set_if_present("APP_DATA_DIR", ("APP_DATA_DIR",))
        _set_if_present("APP_LOG_DIR", ("APP_LOG_DIR",))
        _set_if_present("APP_RUNTIME_DIR", ("APP_RUNTIME_DIR",))
        _set_if_present("APP_PUBLIC_BASE_URL", ("APP_PUBLIC_BASE_URL",))
        _set_if_present(
            "APP_GRACEFUL_SHUTDOWN_SECONDS",
            ("APP_GRACEFUL_SHUTDOWN_SECONDS",),
        )
        _set_if_present("APP_HOST", ("APP_HOST", "BACKEND_HOST"))
        _set_if_present("APP_PORT", ("APP_PORT", "BACKEND_PORT"))
        _set_if_present("METRICS_ENABLED", ("METRICS_ENABLED",))
        _set_if_present("METRICS_BIND_HOST", ("METRICS_BIND_HOST",))
        _set_if_present("METRICS_PORT", ("METRICS_PORT",))
        _set_if_present("LOCAL_LLM_BASE_URL", ("LOCAL_LLM_BASE_URL", "LLM_LOCAL_QWEN_BASE_URL"))
        _set_if_present("LOCAL_LLM_API_KEY", ("LOCAL_LLM_API_KEY", "LLM_LOCAL_QWEN_API_KEY"))
        _set_if_present("MEMORY_STORE_CONFIG_PATH", ("MEMORY_STORE_CONFIG_PATH", "MEMORY_STORE_CONFIG"))

        if "LOG_FORMAT" not in env and "LOG_JSON" in env:
            env["LOG_FORMAT"] = "json" if env["LOG_JSON"].strip().lower() in {"1", "true", "yes", "on"} else "text"
        elif "LOG_JSON" not in env and "LOG_FORMAT" in env:
            normalized = env["LOG_FORMAT"].strip().lower()
            env["LOG_JSON"] = "true" if normalized == "json" else "false"

        return env


def load_settings(*, env_file: str | Path | None = ENV_FILE_PATH) -> Settings:
    """Load settings using the backend-local .env file by default."""

    class LoadedSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=str(env_file) if env_file is not None else None,
            env_file_encoding="utf-8",
            extra="ignore",
            populate_by_name=True,
        )

    return LoadedSettings()
