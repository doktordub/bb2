from __future__ import annotations

import pytest

from app.session.errors import InvalidSessionIdError, SessionIdRequiredError
from app.session.identifiers import (
    PrefixedUuidSessionIdProvider,
    normalize_session_id,
    resolve_session_id,
)
from app.testing.fakes.fake_session_id_provider import FakeSessionIdProvider


def test_prefixed_uuid_session_id_provider_generates_prefixed_ids() -> None:
    provider = PrefixedUuidSessionIdProvider(prefix="session")

    session_id = provider.new_session_id()

    assert session_id.startswith("session_")
    assert normalize_session_id(session_id) == session_id


def test_fake_session_id_provider_generates_deterministic_sequence() -> None:
    provider = FakeSessionIdProvider()

    assert provider.new_session_id() == "session_0001"
    assert provider.new_session_id() == "session_0002"


def test_normalize_session_id_rejects_invalid_shape() -> None:
    with pytest.raises(InvalidSessionIdError):
        normalize_session_id("bad id with spaces")


def test_resolve_session_id_requires_explicit_value_when_generation_disabled() -> None:
    with pytest.raises(SessionIdRequiredError):
        resolve_session_id(
            None,
            generate_when_missing=False,
            id_provider=FakeSessionIdProvider(),
        )