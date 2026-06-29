from __future__ import annotations

import pytest

from app.tools.errors import ToolArgumentValidationError
from app.tools.models import ResolvedToolDefinition
from app.tools.schema_validation import ToolArgumentValidator


def build_definition() -> ResolvedToolDefinition:
    return ResolvedToolDefinition(
        logical_name="documents.search",
        mcp_tool_name="documents.search",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "maxLength": 32},
                "limit": {"type": "integer", "enum": [1, 5, 10]},
                "filters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 2,
                },
            },
            "additionalProperties": False,
        },
        max_argument_bytes=256,
        metadata={"denylisted_fields": ["raw_auth_header"]},
    )


def test_argument_validator_accepts_valid_arguments() -> None:
    validator = ToolArgumentValidator(default_max_argument_bytes=512)

    validated = validator.validate(
        build_definition(),
        {"query": "architecture", "limit": 5, "filters": ["mcp"]},
    )

    assert validated == {"query": "architecture", "limit": 5, "filters": ["mcp"]}


@pytest.mark.parametrize(
    ("arguments", "expected_message"),
    [
        ({"limit": 5}, "arguments.query is required"),
        ({"query": "ok", "api_token": "secret"}, "secret-like fields"),
        ({"query": "ok", "raw_auth_header": "Bearer abc"}, "denylisted fields"),
        ({"query": "x" * 400}, "size limit"),
    ],
)
def test_argument_validator_rejects_invalid_arguments(
    arguments: dict[str, object],
    expected_message: str,
) -> None:
    validator = ToolArgumentValidator(default_max_argument_bytes=512)

    with pytest.raises(ToolArgumentValidationError, match=expected_message):
        validator.validate(build_definition(), arguments)
