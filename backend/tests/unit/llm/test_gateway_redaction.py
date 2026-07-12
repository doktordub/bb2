from __future__ import annotations

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.models import ProviderLLMResponse
from app.llm.providers.fake import FakeLLMProviderAdapter, FakeProviderCall
from app.testing.fakes import FakeTraceStore
from tests.unit.llm.support import base_config, build_context, build_gateway, build_registry


async def test_gateway_trace_payloads_redact_prompts_and_completions_by_default() -> None:
    config = base_config(trace_payloads_enabled=True, trace_prompts=False, trace_completions=False)
    trace_store = FakeTraceStore()
    gateway = build_gateway(config)
    context = build_context(config, trace_store=trace_store)

    await gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="secret prompt text")],
            metadata={"api_key": "super-secret-key"},
        ),
        context,
    )

    started_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_started")
    completed_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_completed")

    assert "messages" not in started_event.payload
    assert started_event.payload["message_count"] == 1
    assert completed_event.payload["raw_id_present"] is True
    assert "text" not in completed_event.payload


async def test_gateway_trace_payloads_include_prompt_and_completion_when_enabled() -> None:
    config = base_config(trace_payloads_enabled=True, trace_prompts=True, trace_completions=True)
    trace_store = FakeTraceStore()
    gateway = build_gateway(config)
    context = build_context(config, trace_store=trace_store)

    await gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="visible prompt")]),
        context,
    )

    started_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_started")
    completed_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_completed")

    assert started_event.payload["messages"] == ["visible prompt"]
    assert completed_event.payload["text"] == "primary answer"


async def test_gateway_trace_payloads_include_safe_tool_fields_without_raw_tool_data() -> None:
    class ToolCallingProvider(FakeLLMProviderAdapter):
        async def complete(self, request):  # type: ignore[override]
            self.calls.append(FakeProviderCall(request=request, mode="complete"))
            return ProviderLLMResponse(
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
                raw_id=f"{self.name}-response",
            )

    config = base_config(trace_payloads_enabled=True, trace_prompts=False, trace_completions=False)
    assert isinstance(config["llm"], dict)
    assert isinstance(config["llm"]["profiles"], dict)
    config["llm"]["profiles"]["primary_profile"]["supports_tool_calling"] = True
    config["llm"]["profiles"]["fallback_profile"]["supports_tool_calling"] = True
    trace_store = FakeTraceStore()
    registry = build_registry(
        config,
        primary_adapter=ToolCallingProvider(name="primary_provider", supports_tool_calling=True),
    )
    gateway = build_gateway(config, registry=registry)
    context = build_context(config, trace_store=trace_store)

    await gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="Find architecture notes.")],
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
            tool_choice="auto",
        ),
        context,
    )

    started_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_started")
    completed_event = next(event for event in trace_store.events if event.resolved_event_name == "llm_call_completed")

    assert started_event.payload["tool_count"] == 1
    assert started_event.payload["tool_names"] == ("documents.search",)
    assert started_event.payload["tool_choice_mode"] == "auto"
    assert started_event.payload["has_assistant_tool_calls"] is False
    assert started_event.payload["has_tool_result_messages"] is False
    assert "messages" not in started_event.payload
    assert '"query": "architecture notes"' not in repr(started_event.payload)

    assert completed_event.payload["finish_reason"] == "tool_calls"
    assert completed_event.payload["tool_call_count"] == 1
    assert completed_event.payload["tool_call_names"] == ("documents.search",)
    assert completed_event.payload["text_present"] is False
    assert "text" not in completed_event.payload
    assert '"query": "architecture notes"' not in repr(completed_event.payload)