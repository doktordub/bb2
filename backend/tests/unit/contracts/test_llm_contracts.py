from app.contracts.llm import (
    LLMContentPart,
    LLMHealthResult,
    LLMMessage,
    LLMProfileHealthSummary,
    LLMProfileSummary,
    LLMProviderHealthSummary,
    LLMRequest,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMStreamEvent,
    LLMToolCall,
    LLMToolChoice,
    LLMToolDefinition,
)


def test_llm_request_normalizes_legacy_aliases_and_response_format() -> None:
    request = LLMRequest(
        component="agent.support",
        messages=[LLMMessage(role="user", content="hello")],
        max_tokens=128,
        response_format={
            "type": "json_schema",
            "schema_name": "answer",
            "json_schema": {"type": "object"},
            "strict": True,
        },
    )

    assert request.max_tokens == 128
    assert request.max_output_tokens == 128
    assert isinstance(request.response_format, LLMResponseFormat)
    assert request.response_format.type == "json_schema"
    assert request.response_format.schema_name == "answer"


def test_llm_message_supports_structured_content_parts() -> None:
    message = LLMMessage(
        role="user",
        content=[
            {"type": "text", "text": "hello"},
            {"type": "json", "json_value": {"topic": "contracts"}},
        ],
    )

    assert isinstance(message.content, list)
    assert message.content[0] == LLMContentPart(type="text", text="hello")
    assert message.content[1].json_value == {"topic": "contracts"}


def test_llm_stream_delta_converts_to_lifecycle_events() -> None:
    delta_event = LLMStreamDelta(text_delta="hi", profile="fast").as_event()
    completed_event = LLMStreamDelta(
        text_delta="done",
        profile="fast",
        is_final=True,
    ).as_event()

    assert delta_event == LLMStreamEvent.delta(text="hi", profile="fast")
    assert completed_event.type == "completed"
    assert completed_event.profile == "fast"


def test_llm_request_normalizes_native_tool_calling_fields() -> None:
    request = LLMRequest(
        component="agent.support",
        messages=[LLMMessage(role="user", content="search the docs")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "documents.search",
                    "description": "Search project documents.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "documents.search"}},
    )

    assert len(request.tools) == 1
    assert isinstance(request.tools[0], LLMToolDefinition)
    assert request.tools[0].function.name == "documents.search"
    assert isinstance(request.tool_choice, LLMToolChoice)
    assert request.tool_choice.type == "function"
    assert request.tool_choice.function is not None
    assert request.tool_choice.function.name == "documents.search"


def test_llm_message_response_and_stream_event_normalize_tool_calls() -> None:
    tool_call = {
        "id": "call_docs_1",
        "type": "function",
        "function": {
            "name": "documents.search",
            "arguments": '{"query":"gateway path"}',
        },
    }

    message = LLMMessage(
        role="assistant",
        content="",
        tool_calls=[tool_call],
    )
    response = LLMStreamEvent.completed(
        profile="local_reasoning",
        provider="local_provider",
        model="local-model",
        tool_calls=[tool_call],
        finish_reason="tool_calls",
        reasoning={"effort": "medium"},
    )

    assert isinstance(message.tool_calls[0], LLMToolCall)
    assert message.tool_calls[0].function.arguments == '{"query":"gateway path"}'
    assert response.tool_calls[0].function.name == "documents.search"
    assert response.reasoning == {"effort": "medium"}


def test_llm_health_and_profile_summary_models_are_safe_and_typed() -> None:
    health = LLMHealthResult(
        status="ok",
        providers_configured=True,
        profiles_configured=True,
        default_profile="default_chat",
        providers={
            "local_qwen": LLMProviderHealthSummary(
                status="ok",
                type="openai_compatible",
                enabled=True,
            )
        },
        profiles={
            "default_chat": LLMProfileHealthSummary(
                status="ok",
                provider="local_qwen",
                enabled=True,
                supports_streaming=True,
            )
        },
    )
    summary = LLMProfileSummary(
        name="default_chat",
        provider="local_qwen",
        model="qwen-test",
        enabled=True,
        supports_streaming=True,
        supports_json_schema=False,
        supports_tool_calling=False,
        fallback_profiles=("fallback_chat",),
        allowed_for={"usecases": ("default_chat",)},
    )

    assert health.providers["local_qwen"].type == "openai_compatible"
    assert health.profiles["default_chat"].supports_streaming is True
    assert summary.fallback_profiles == ("fallback_chat",)
    assert summary.allowed_for["usecases"] == ("default_chat",)