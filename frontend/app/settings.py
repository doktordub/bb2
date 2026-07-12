from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = FRONTEND_ROOT.parent
DEFAULT_HELP_MARKDOWN_PATH = WORKSPACE_ROOT / "docs" / "Training_Readme.md"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _parse_positive_int(value: str | None, default: int) -> int:
    parsed = _parse_int(value, default)
    return parsed if parsed > 0 else default


def _resolve_path(value: str | None, default_path: Path) -> Path:
    if not value:
        return default_path.resolve()

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = FRONTEND_ROOT / candidate
    return candidate.resolve()


def _normalize_backend_base_url(value: str | None) -> str:
    base_url = (value or "http://127.0.0.1:8000").strip()
    stripped = base_url.rstrip("/")
    return stripped or "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class FrontendVisualizationLimits:
    max_artifacts_per_response: int = 3
    max_rows_inline: int = 5000
    max_series: int = 12
    max_categories: int = 100


@dataclass(frozen=True, slots=True)
class Settings:
    frontend_env: str
    frontend_host: str
    frontend_port: int
    frontend_debug: bool
    frontend_testing: bool
    frontend_secret_key: str
    backend_base_url: str
    backend_timeout_seconds: int
    backend_stream_timeout_seconds: int
    frontend_admin_enabled: bool
    frontend_debug_traces_enabled: bool
    frontend_restart_enabled: bool
    frontend_help_markdown_path: Path
    frontend_static_version: str
    frontend_visualization_limits: FrontendVisualizationLimits = field(
        default_factory=FrontendVisualizationLimits
    )

    def as_flask_config(self) -> dict[str, object]:
        return {
            "ENV": self.frontend_env,
            "DEBUG": self.frontend_debug,
            "TESTING": self.frontend_testing,
            "SECRET_KEY": self.frontend_secret_key,
            "FRONTEND_SETTINGS": self,
        }


def load_settings(
    env_file: str | Path | None = None,
    *,
    load_env: bool = True,
) -> Settings:
    if load_env:
        candidate = Path(env_file) if env_file is not None else FRONTEND_ROOT / ".env"
        if candidate.exists():
            load_dotenv(candidate, override=False)

    return Settings(
        frontend_env=os.getenv("FRONTEND_ENV", "local"),
        frontend_host=os.getenv("FRONTEND_HOST", "127.0.0.1"),
        frontend_port=_parse_int(os.getenv("FRONTEND_PORT"), 5000),
        frontend_debug=_parse_bool(os.getenv("FRONTEND_DEBUG"), False),
        frontend_testing=_parse_bool(os.getenv("FRONTEND_TESTING"), False),
        frontend_secret_key=os.getenv("FRONTEND_SECRET_KEY", "dev-only-change-me"),
        backend_base_url=_normalize_backend_base_url(os.getenv("BACKEND_BASE_URL")),
        backend_timeout_seconds=_parse_int(os.getenv("BACKEND_TIMEOUT_SECONDS"), 90),
        backend_stream_timeout_seconds=_parse_int(
            os.getenv("BACKEND_STREAM_TIMEOUT_SECONDS"),
            300,
        ),
        frontend_admin_enabled=_parse_bool(os.getenv("FRONTEND_ADMIN_ENABLED"), True),
        frontend_debug_traces_enabled=_parse_bool(
            os.getenv("FRONTEND_DEBUG_TRACES_ENABLED"),
            True,
        ),
        frontend_restart_enabled=_parse_bool(os.getenv("FRONTEND_RESTART_ENABLED"), False),
        frontend_help_markdown_path=_resolve_path(
            os.getenv("FRONTEND_HELP_MARKDOWN_PATH"),
            DEFAULT_HELP_MARKDOWN_PATH,
        ),
        frontend_static_version=os.getenv("FRONTEND_STATIC_VERSION", "local-dev").strip()
        or "local-dev",
        frontend_visualization_limits=FrontendVisualizationLimits(
            max_artifacts_per_response=_parse_positive_int(
                os.getenv("FRONTEND_VISUALIZATION_MAX_ARTIFACTS_PER_RESPONSE"),
                3,
            ),
            max_rows_inline=_parse_positive_int(
                os.getenv("FRONTEND_VISUALIZATION_MAX_ROWS_INLINE"),
                5000,
            ),
            max_series=_parse_positive_int(
                os.getenv("FRONTEND_VISUALIZATION_MAX_SERIES"),
                12,
            ),
            max_categories=_parse_positive_int(
                os.getenv("FRONTEND_VISUALIZATION_MAX_CATEGORIES"),
                100,
            ),
        ),
    )