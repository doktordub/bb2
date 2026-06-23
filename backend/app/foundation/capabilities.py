"""Foundation-safe capability discovery."""

from typing import Any

from app.config.settings import Settings


class CapabilitiesService:
    """Expose the backend feature surface without leaking implementation details."""

    def __init__(self, *, settings: Settings, raw_config: dict[str, Any]) -> None:
        self._settings = settings
        self._raw_config = raw_config

    def describe(self) -> dict[str, Any]:
        return {
            "service": self._settings.app_name,
            "capabilities": {
                "chat": False,
                "streaming": False,
                "session_reset": False,
                "mcp_tools": False,
                "memory": False,
                "llm_profiles": False,
                "trace": False,
            },
        }