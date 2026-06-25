from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import Enum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from app.persistence.serialization import dumps_json, to_jsonable


class Color(Enum):
    RED = "red"


@dataclass(frozen=True, slots=True)
class ExampleDataclass:
    title: str
    created_at: datetime


class ExampleModel(BaseModel):
    value: int


class UnsupportedValue:
    pass


def test_to_jsonable_handles_supported_runtime_types() -> None:
    payload = {
        "dataclass": ExampleDataclass(
            title="sample",
            created_at=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
        ),
        "date": date(2026, 6, 24),
        "time": time(12, 30, 15),
        "enum": Color.RED,
        "set": {"b", "a"},
        "tuple": (1, 2),
        "path": Path("data/trace.db"),
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "model": ExampleModel(value=7),
        "unsupported": UnsupportedValue(),
    }

    assert to_jsonable(payload) == {
        "dataclass": {
            "title": "sample",
            "created_at": "2026-06-24T12:00:00+00:00",
        },
        "date": "2026-06-24",
        "time": "12:30:15",
        "enum": "red",
        "set": ["a", "b"],
        "tuple": [1, 2],
        "path": "data/trace.db",
        "uuid": "12345678-1234-5678-1234-567812345678",
        "model": {"value": 7},
        "unsupported": "<UnsupportedValue>",
    }


def test_dumps_json_returns_compact_ascii_safe_payload() -> None:
    payload = {
        "tuple": (1, 2),
        "set": {"b", "a"},
        "bytes": b"hello",
    }

    assert dumps_json(payload) == '{"tuple":[1,2],"set":["a","b"],"bytes":"hello"}'