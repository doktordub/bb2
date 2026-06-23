"""Foundation-safe capability discovery."""

from typing import Any

from app.contracts.config import ConfigurationView
from app.config.settings import Settings


class CapabilitiesService:
    """Expose the backend feature surface without leaking implementation details."""

    def __init__(self, *, settings: Settings, config: ConfigurationView) -> None:
        self._settings = settings
        self._config = config

    def describe(self) -> dict[str, Any]:
        features = self._config.section("features")
        enabled_usecases = self._enabled_usecases()

        return {
            "service": self._config.require("app.name"),
            "capabilities": {
                "chat": bool(enabled_usecases),
                "streaming": bool(features.get("streaming_enabled", False)) and bool(enabled_usecases),
                "session_reset": bool(enabled_usecases)
                and self._has_provider("persistence.workflow_state.provider"),
                "mcp_tools": bool(features.get("tools_enabled", False))
                and bool(enabled_usecases)
                and bool(self._config.get("mcp.main.url")),
                "memory": bool(features.get("memory_enabled", False))
                and self._has_provider("persistence.memory.provider"),
                "llm_profiles": bool(self._config.section("llm.profiles")),
                "trace": bool(features.get("trace_enabled", False))
                and self._has_provider("persistence.trace.provider"),
            },
        }

    def _enabled_usecases(self) -> dict[str, dict[str, Any]]:
        usecases = self._config.section("usecases")
        return {
            name: usecase
            for name, usecase in usecases.items()
            if isinstance(usecase, dict) and bool(usecase.get("enabled", True))
        }

    def _has_provider(self, path: str) -> bool:
        value = self._config.get(path)
        return isinstance(value, str) and value.strip() != ""