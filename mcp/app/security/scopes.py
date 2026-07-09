"""Helpers for extracting normalized auth scopes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


SCOPE_CLAIM_NAMES = ("scope", "scp", "scopes", "permissions")


def normalize_scopes(value: Any) -> tuple[str, ...]:
    """Normalize scope claims into a unique ordered tuple."""

    items: list[str]
    if value is None:
        return ()
    if isinstance(value, str):
        items = value.replace(",", " ").split()
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str, Mapping)):
        items = [str(item) for item in value]
    else:
        return ()

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return tuple(normalized)


def extract_scopes(claims: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract scopes from common OAuth and JWT claim names."""

    for claim_name in SCOPE_CLAIM_NAMES:
        scopes = normalize_scopes(claims.get(claim_name))
        if scopes:
            return scopes
    return ()