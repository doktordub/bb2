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