from app.config.redaction import REDACTED_VALUE, redact_config


def test_redact_config_redacts_nested_sensitive_values() -> None:
    original = {
        "llm": {
            "providers": {
                "openai": {
                    "api_key": "top-secret-key",
                    "default_headers": {
                        "Authorization": "Bearer top-secret-token",
                    },
                }
            }
        },
        "persistence": {
            "memory": {
                "config": {
                    "credentials": {
                        "username": "service-user",
                        "password": "super-secret-password",
                    }
                }
            }
        },
        "agents": [
            {
                "name": "support_agent",
                "metadata": {
                    "session_token": "abc123",
                },
            }
        ],
        "safe_value": "visible",
    }

    redacted = redact_config(original)

    assert redacted == {
        "llm": {
            "providers": {
                "openai": {
                    "api_key": REDACTED_VALUE,
                    "default_headers": {
                        "Authorization": REDACTED_VALUE,
                    },
                }
            }
        },
        "persistence": {
            "memory": {
                "config": {
                    "credentials": {
                        "username": REDACTED_VALUE,
                        "password": REDACTED_VALUE,
                    }
                }
            }
        },
        "agents": [
            {
                "name": "support_agent",
                "metadata": {
                    "session_token": REDACTED_VALUE,
                },
            }
        ],
        "safe_value": "visible",
    }
    assert original["llm"]["providers"]["openai"]["api_key"] == "top-secret-key"


def test_redact_config_preserves_non_sensitive_sequences() -> None:
    redacted = redact_config(
        {
            "allowed_tools": ["documents.search", "calculator.run"],
            "fallback_profiles": ("cloud_fast", "local_reasoning"),
        }
    )

    assert redacted == {
        "allowed_tools": ["documents.search", "calculator.run"],
        "fallback_profiles": ("cloud_fast", "local_reasoning"),
    }