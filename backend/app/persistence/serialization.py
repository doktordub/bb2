"""JSON-safe serialization helpers for persistence adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.persistence.errors import PersistenceSerializationError


def to_jsonable(value: object) -> Any:
    """Convert runtime values into JSON-safe structures for persistence."""

    try:
        return _to_jsonable(value)
    except PersistenceSerializationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise PersistenceSerializationError("Failed to serialize persistence payload.") from exc


def dumps_json(value: object) -> str:
    """Serialize a runtime value into compact ASCII-safe JSON."""

    try:
        return json.dumps(to_jsonable(value), ensure_ascii=True, separators=(",", ":"))
    except TypeError as exc:
        raise PersistenceSerializationError("Failed to encode persistence JSON.") from exc


def dumps_canonical_json(value: object) -> str:
    """Serialize a runtime value into stable sorted-key JSON."""

    try:
        return json.dumps(
            to_jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError as exc:
        raise PersistenceSerializationError("Failed to encode canonical persistence JSON.") from exc


def hash_canonical_json(value: object) -> str:
    """Return a stable SHA-256 digest for a JSON-safe runtime value."""

    return hashlib.sha256(dumps_canonical_json(value).encode("utf-8")).hexdigest()


def extract_message_count(state: Mapping[str, object]) -> int:
    """Derive the stored conversation message count from workflow state."""

    conversation = state.get("conversation")
    if not isinstance(conversation, Mapping):
        return 0

    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return 0

    return len(messages)


def extract_current_step(state: Mapping[str, object]) -> str | None:
    """Derive the current workflow step from workflow state."""

    workflow = state.get("workflow")
    if not isinstance(workflow, Mapping):
        return None

    value = workflow.get("current_step")
    return value if isinstance(value, str) else None


def extract_checkpoint_name(state: Mapping[str, object]) -> str | None:
    """Derive the active checkpoint name from workflow state."""

    workflow = state.get("workflow")
    if not isinstance(workflow, Mapping):
        return None

    checkpoint = workflow.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        return None

    value = checkpoint.get("name")
    return value if isinstance(value, str) else None


def _to_jsonable(value: object) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value

    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]

    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]

    if isinstance(value, set | frozenset):
        return [_to_jsonable(item) for item in sorted(value, key=_sort_key)]

    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))

    if isinstance(value, BaseModel):
        return _to_jsonable(value.model_dump(mode="python"))

    if isinstance(value, datetime | date | time):
        return value.isoformat()

    if isinstance(value, Path):
        return value.as_posix()

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, Enum):
        return _to_jsonable(value.value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return f"<{type(value).__name__}>"


def _sort_key(value: object) -> str:
    return f"{type(value).__name__}:{value!s}"