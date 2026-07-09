"""TLS helpers for safe MCP server status reporting."""

from __future__ import annotations

from typing import Any

from app.errors import MCPTLSError
from app.schemas import TLSSettings


def validate_tls_settings(settings: TLSSettings) -> None:
    """Defensive validation for TLS settings at runtime boundaries."""

    if settings.mode == "terminate_here" and (not settings.cert_file or not settings.key_file):
        raise MCPTLSError(
            "TLS termination mode 'terminate_here' requires both cert_file and key_file."
        )


def summarize_tls_settings(settings: TLSSettings) -> dict[str, Any]:
    """Return a safe TLS summary for health and diagnostics."""

    validate_tls_settings(settings)
    return {
        "mode": settings.mode,
        "behind_proxy": settings.behind_proxy,
        "terminate_here_configured": bool(settings.cert_file and settings.key_file),
    }