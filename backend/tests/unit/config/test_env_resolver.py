from __future__ import annotations

import pytest

from app.config.env_resolver import has_env_reference, resolve_env_references
from app.contracts.errors import ConfigurationError


def test_has_env_reference_detects_supported_placeholders() -> None:
    assert has_env_reference("${env:OPENAI_API_KEY}") is True
    assert has_env_reference("prefix-${env:APP_DATA_DIR:./data}-suffix") is True
    assert has_env_reference("plain text") is False


def test_resolve_env_references_supports_embedded_values() -> None:
    resolved = resolve_env_references(
        {
            "path": "${env:APP_DATA_DIR:./data}/trace.db",
            "endpoint": "http://${env:HOST:127.0.0.1}:${env:PORT:8000}/v1",
        },
        env={"HOST": "localhost", "PORT": "9001"},
    )

    assert resolved == {
        "path": "./data/trace.db",
        "endpoint": "http://localhost:9001/v1",
    }


def test_resolve_env_references_supports_required_and_optional_values() -> None:
    resolved = resolve_env_references(
        {
            "required": "${env:APP_ENV}",
            "with_default": "${env:APP_DATA_DIR:./data}",
            "empty_default": "${env:LOCAL_LLM_API_KEY:}",
        },
        env={"APP_ENV": "local", "APP_DATA_DIR": "backend-data", "LOCAL_LLM_API_KEY": ""},
    )

    assert resolved == {
        "required": "local",
        "with_default": "backend-data",
        "empty_default": "",
    }


def test_resolve_env_references_tracks_nested_paths_in_errors() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_env_references(
            {
                "llm": {
                    "providers": {
                        "openai": {
                            "api_key": "${env:OPENAI_API_KEY}",
                        }
                    }
                }
            },
            env={},
        )

    assert "OPENAI_API_KEY" in str(exc_info.value)
    assert "llm.providers.openai.api_key" in str(exc_info.value)


def test_resolve_env_references_recurses_into_lists_and_tuples() -> None:
    resolved = resolve_env_references(
        {
            "values": ["${env:FIRST}", "${env:SECOND:two}"],
            "pair": ("${env:THIRD:3}", "static"),
        },
        env={"FIRST": "one"},
    )

    assert resolved == {
        "values": ["one", "two"],
        "pair": ("3", "static"),
    }