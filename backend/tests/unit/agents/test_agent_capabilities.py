from __future__ import annotations

import pytest

from app.agents.capabilities import (
    capabilities_from_settings,
    capability_labels,
    require_capability,
    validate_capabilities,
)
from app.agents.errors import AgentCapabilityError
from app.agents.models import AgentCapabilities
from app.config.view import AgentCapabilitySettings


def test_capabilities_from_settings_preserves_enabled_flags() -> None:
    settings = AgentCapabilitySettings(
        answer=True,
        review=True,
        stream=False,
        memory_read=True,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=True,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )

    capabilities = capabilities_from_settings(settings)

    assert capabilities == AgentCapabilities(
        answer=True,
        review=True,
        stream=False,
        memory_read=True,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=True,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    assert capability_labels(capabilities) == (
        "answer",
        "review",
        "memory_read",
        "tool_intents",
    )


def test_validate_capabilities_rejects_invalid_self_managed_settings() -> None:
    with pytest.raises(AgentCapabilityError):
        validate_capabilities(AgentCapabilities(answer=True, self_managed_tools=True))


def test_require_capability_rejects_disabled_and_unknown_capabilities() -> None:
    capabilities = AgentCapabilities(answer=True, stream=False)

    with pytest.raises(AgentCapabilityError):
        require_capability(capabilities, "stream", agent_name="assistant")

    with pytest.raises(AgentCapabilityError):
        require_capability(capabilities, "unknown_capability", agent_name="assistant")