"""Configuration helpers for backend foundation."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BACKEND_ROOT": ("app.config.settings", "BACKEND_ROOT"),
    "ConfigLoadError": ("app.config.loader", "ConfigLoadError"),
    "Settings": ("app.config.settings", "Settings"),
    "load_raw_config": ("app.config.loader", "load_raw_config"),
    "load_settings": ("app.config.settings", "load_settings"),
    "resolve_backend_path": ("app.config.loader", "resolve_backend_path"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attribute_name)
