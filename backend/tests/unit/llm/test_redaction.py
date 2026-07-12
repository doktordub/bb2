from __future__ import annotations

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.models import ProviderLLMResponse
from app.llm.profile_resolver import LLMProfileResolver
from app.llm.redaction import summarize_provider_response, summarize_request
from tests.unit.llm.support import base_config, build_context


def test_summarize_request_includes_safe_tool_metadata_without_prompt_capture() -> None:
    config = base_config()
    assert isinstance(config["llm"], dict)
    assert isinstance(config["llm"]["profiles"], dict)
    config["llm"]["profiles"]["primary_profile"]["supports_tool_calling"] = True
    context = build_context(config)
    request = LLMRequest(
        messages=[
            LLMMessage(role="user", content="Search architecture notes."),
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "call_documents_search_1",
                        "function": {
                            "name": "documents.search",
                            "arguments": '{"query": "architecture notes"}',
                        },
                    }
                ],
            ),
            LLMMessage(
                role="tool",
                content="Confidential tool output.",
                tool_call_id="call_documents_search_1",
            ),
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "documents.search",
                    "description": "Search architecture documents.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        tool_choice={
            "type": "function",
            "function": {"name": "documents.search"},
        },
    )
    resolved = LLMProfileResolver().resolve(request=request, context=context)

    payload = summarize_request(request, resolved=resolved)

    assert payload["tool_count"] == 1
    assert payload["tool_names"] == ("documents.search",)
    assert payload["tool_choice_mode"] == "function"
    assert payload["tool_choice_name"] == "documents.search"
    assert payload["has_assistant_tool_calls"] is True
    assert payload["assistant_tool_call_count"] == 1
    assert payload["has_tool_result_messages"] is True
    assert payload["tool_result_message_count"] == 1
    assert "messages" not in payload
    serialized = repr(payload)
    assert '"query": "architecture notes"' not in serialized
    assert "Confidential tool output." not in serialized


def test_summarize_provider_response_includes_safe_tool_metadata_without_completion_capture() -> None:
    payload = summarize_provider_response(
        ProviderLLMResponse(
            text="",
            tool_calls=[
                {
                    "id": "call_documents_search_1",
                    "function": {
                        "name": "documents.search",
                        "arguments": '{"query": "architecture notes"}',
                    },
                }
            ],
            finish_reason="tool_calls",
            raw_id="response_1",
        ),
        include_text=False,
    )

    assert payload["finish_reason"] == "tool_calls"
    assert payload["raw_id_present"] is True
    assert payload["tool_call_count"] == 1
    assert payload["tool_call_names"] == ("documents.search",)
    assert payload["text_present"] is False
    assert "text" not in payload
    assert '"query": "architecture notes"' not in repr(payload)