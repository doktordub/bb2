"""Tool-specific redaction and secret-key detection helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.observability.redaction import Redactor, is_sensitive_key

_NO_CONTROL_KEYS = frozenset[str]()


def is_secret_like_tool_key(key: object) -> bool:
    """Return True when a tool argument or result key looks credential-like."""

    return is_sensitive_key(key, non_sensitive_control_keys=_NO_CONTROL_KEYS)


def find_secret_like_paths(
    value: object,
    *,
    path: tuple[str, ...] = (),
) -> tuple[tuple[str, ...], ...]:
    """Return all nested key paths that look like credentials or auth fields."""

    matches: list[tuple[str, ...]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            next_path = path + (key_text,)
            if is_secret_like_tool_key(key_text):
                matches.append(next_path)
            matches.extend(find_secret_like_paths(item, path=next_path))
        return tuple(matches)

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            matches.extend(find_secret_like_paths(item, path=path + (str(index),)))
    return tuple(matches)


def redact_tool_payload(value: object, *, max_chars: int | None = None) -> object:
    """Return a redacted, JSON-safe payload for tool metadata or results."""

    return Redactor(redact_secrets=True, max_chars=max_chars).redact(value)


def format_paths(paths: Sequence[Sequence[str]]) -> str:
    """Render nested paths in a stable, readable form."""

    rendered: list[str] = []
    for raw_path in paths:
        if not raw_path:
            continue
        current = raw_path[0]
        for part in raw_path[1:]:
            if part.isdigit():
                current = f"{current}[{part}]"
            else:
                current = f"{current}.{part}"
        rendered.append(current)
    return ", ".join(rendered)
