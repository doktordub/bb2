from __future__ import annotations

import pytest

from app.bootstrap import bootstrap
from app.errors import ToolInputValidationError
from app.security.arguments import assert_no_secret_like_arguments


def test_argument_detection_rejects_nested_secret_keys_and_jwt_values() -> None:
    with pytest.raises(ToolInputValidationError, match="must not include secret-like"):
        assert_no_secret_like_arguments(
            {
                "payload": {
                    "api_key": "abc123",
                    "nested": [
                        {"note": "safe"},
                        {"value": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiYWNrZW5kIn0.signature"},
                    ],
                }
            },
            tool_name="example.echo",
        )


@pytest.mark.asyncio
async def test_websearch_tool_rejects_secret_like_query_before_provider_execution() -> None:
    runtime = bootstrap()

    with pytest.raises(Exception, match="must not include secret-like"):
        await runtime.server.call_tool(
            "websearch.search",
            {
                "query": "Bearer abcdefghijklmnopqrstuvwxy",
                "max_results": 1,
            },
        )