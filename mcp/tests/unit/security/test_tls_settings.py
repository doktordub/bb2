from __future__ import annotations

import pytest

from app.errors import MCPTLSError
from app.schemas import TLSSettings
from app.security.tls import summarize_tls_settings, validate_tls_settings


def test_tls_summary_reports_upstream_termination_safely() -> None:
    settings = TLSSettings(mode="terminate_upstream", cert_file=None, key_file=None, behind_proxy=True)

    assert summarize_tls_settings(settings) == {
        "mode": "terminate_upstream",
        "behind_proxy": True,
        "terminate_here_configured": False,
    }


def test_tls_helper_rejects_missing_certificates_for_local_termination() -> None:
    settings = TLSSettings.model_construct(
        mode="terminate_here",
        cert_file=None,
        key_file=None,
        behind_proxy=False,
    )

    with pytest.raises(MCPTLSError, match="terminate_here"):
        validate_tls_settings(settings)