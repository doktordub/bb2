"""Backend settings with deterministic backend-root-relative env loading."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = BACKEND_ROOT / ".env"


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

    host: str = Field(default="127.0.0.1", validation_alias="BACKEND_HOST")
    port: int = Field(default=8000, validation_alias="BACKEND_PORT")
    reload: bool = Field(default=False, validation_alias="BACKEND_RELOAD")

    app_usecase: str | None = Field(default=None, validation_alias="APP_USECASE")
    app_config_path: str | None = Field(default=None, validation_alias="APP_CONFIG_PATH")
    app_config_strict: bool = Field(default=False, validation_alias="APP_CONFIG_STRICT")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_json: bool = Field(default=True, validation_alias="LOG_JSON")

    docs_url: str | None = "/docs"
    redoc_url: str | None = "/redoc"

    mcp_main_url: str | None = Field(default=None, validation_alias="MCP_MAIN_URL")
    llm_local_qwen_base_url: str | None = Field(
        default=None,
        validation_alias="LLM_LOCAL_QWEN_BASE_URL",
    )
    llm_local_qwen_api_key: str | None = Field(
        default=None,
        validation_alias="LLM_LOCAL_QWEN_API_KEY",
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    memory_store_config: str | None = Field(default=None, validation_alias="MEMORY_STORE_CONFIG")
    sqlite_workflow_state_url: str | None = Field(
        default=None,
        validation_alias="SQLITE_WORKFLOW_STATE_URL",
    )
    sqlite_trace_url: str | None = Field(default=None, validation_alias="SQLITE_TRACE_URL")


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
