"""Raw config loading helpers for the backend foundation phase."""

from pathlib import Path
from typing import Any

import yaml

from app.config.settings import BACKEND_ROOT


class ConfigLoadError(RuntimeError):
    """Raised when a config file cannot be loaded safely."""


def resolve_backend_path(path: str | Path | None) -> Path | None:
    """Resolve a path against backend/ so callers do not depend on the shell cwd."""

    if path is None:
        return None

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate

    return candidate.resolve(strict=False)


def load_raw_config(
    path: str | None,
    *,
    active_usecase: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Load a YAML mapping when available without requiring config during foundation startup."""

    resolved_path = resolve_backend_path(path)
    payload: dict[str, Any] = {
        "active_usecase": active_usecase,
        "source_path": str(resolved_path) if resolved_path is not None else None,
        "config": {},
    }

    if resolved_path is None:
        return payload

    if not resolved_path.exists():
        if strict:
            raise ConfigLoadError(f"Config file does not exist: {resolved_path}")
        return payload

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            loaded_data: Any = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise ConfigLoadError(f"Failed to read config file: {resolved_path}") from exc

    if not isinstance(loaded_data, dict):
        raise ConfigLoadError("Config file must contain a YAML mapping at the root.")

    payload["config"] = loaded_data
    return payload
