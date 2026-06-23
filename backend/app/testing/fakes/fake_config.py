"""In-memory fake configuration view and loader for contract-focused tests."""

from __future__ import annotations

from typing import Any

from app.contracts.errors import ConfigurationError


class FakeConfigurationView:
    """Deterministic configuration view backed by a nested dictionary."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, path: str, default: Any = None) -> Any:
        if path == "":
            return self.values

        current: Any = self.values
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def require(self, path: str) -> Any:
        value = self.get(path, None)
        if value is None:
            raise ConfigurationError(f"Missing required config path: {path}")
        return value

    def section(self, path: str) -> dict[str, Any]:
        value = self.get(path, {})
        if not isinstance(value, dict):
            raise ConfigurationError(f"Config path is not a section: {path}")
        return dict(value)


class FakeConfigurationLoader:
    """Deterministic async loader that returns a prebuilt fake view."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.view = FakeConfigurationView(values)
        self.load_calls = 0

    async def load(self) -> FakeConfigurationView:
        self.load_calls += 1
        return self.view