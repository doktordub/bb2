"""Cancellation helpers for orchestration runtime turn execution."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from app.orchestration.errors import OrchestrationCancelledError


def is_cancellation_requested(token: object | None) -> bool:
    """Return whether the supplied runtime cancellation token is in a cancelled state."""

    if token is None:
        return False
    if isinstance(token, asyncio.Event):
        return token.is_set()
    if isinstance(token, Mapping):
        return bool(token.get("cancelled") or token.get("is_cancelled") or token.get("is_set"))

    for attribute in ("is_cancelled", "cancelled", "is_set"):
        member = getattr(token, attribute, None)
        if callable(member):
            try:
                return bool(member())
            except TypeError:
                continue
        if isinstance(member, bool):
            return member
    return False


def raise_if_cancelled(token: object | None) -> None:
    """Raise the normalized orchestration cancellation error when cancellation is requested."""

    if is_cancellation_requested(token):
        raise OrchestrationCancelledError()