"""Read-only configuration contracts for runtime code."""

from __future__ import annotations

from typing import Any, Protocol


class ConfigurationView(Protocol):
    """Read-only configuration view used by runtime code."""

    def get(self, path: str, default: Any = None) -> Any:
        ...

    def require(self, path: str) -> Any:
        ...

    def section(self, path: str) -> dict[str, Any]:
        ...


class ConfigurationLoader(Protocol):
    """Async configuration loader contract."""

    async def load(self) -> ConfigurationView:
        ...