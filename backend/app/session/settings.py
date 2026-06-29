"""Session-facing accessors for resolved session settings."""

from app.config.view import SessionSettings, get_session_settings
from app.contracts.config import ConfigurationView

__all__ = ("SessionSettings", "resolve_session_settings")


def resolve_session_settings(config: ConfigurationView) -> SessionSettings:
    """Resolve typed session settings from a generic configuration view."""

    return get_session_settings(config)