"""Backend-local path helpers for persistence adapters."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import BACKEND_ROOT


def resolve_backend_path(path: str | Path) -> Path:
    """Resolve a path relative to backend/ when it is not already absolute."""

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate
    return candidate.resolve(strict=False)


def resolve_data_path(path: str | Path, *, base_dir: Path) -> Path:
    """Resolve a data path relative to the configured persistence base directory."""

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve(strict=False)