from __future__ import annotations

import asyncio

import pytest

from app.orchestration.cancellation import is_cancellation_requested, raise_if_cancelled
from app.orchestration.errors import OrchestrationCancelledError


def test_is_cancellation_requested_supports_events_and_mapping_tokens() -> None:
    event = asyncio.Event()
    assert is_cancellation_requested(event) is False

    event.set()
    assert is_cancellation_requested(event) is True
    assert is_cancellation_requested({"cancelled": True}) is True
    assert is_cancellation_requested({"is_set": False}) is False


def test_raise_if_cancelled_raises_normalized_error() -> None:
    with pytest.raises(OrchestrationCancelledError):
        raise_if_cancelled({"cancelled": True})