from __future__ import annotations

import pytest

from app.contracts.memory import MemoryRecord, MemoryResult, MemoryScope, MemorySearchResult
from app.contracts.state import default_workflow_state
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.gateway import DefaultMemoryGateway
from app.orchestration.errors import OrchestrationDependencyUnavailableError
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.state_delta import workflow_state_snapshot_from_document
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from tests.unit.memory.support import build_memory_settings, build_project_scope_config


class ScopeAwareFakeMemoryAdapter(FakeMemoryAdapter):
    """Test adapter that filters fake results by the full resolved request scope."""

    async def search(self, request: object) -> MemorySearchResult:
        result = await super().search(request)
        request_scope = getattr(request, "scope", MemoryScope()).normalized()
        filtered = [
            item
            for item in result.results
            if item.record is not None and _scopes_match(item.record.scope, request_scope)
        ]
        return MemorySearchResult(
            results=filtered,
            query_id=result.query_id,
            total_candidates=len(filtered),
            search_strategy="scope_aware_fake",
            metadata=dict(result.metadata),
        )


def _scopes_match(stored: MemoryScope, expected: MemoryScope) -> bool:
    normalized_stored = stored.normalized()
    normalized_expected = expected.normalized()
    return all(
        (
            normalized_expected.user_id is None
            or normalized_expected.user_id == normalized_stored.user_id,
            normalized_expected.project_id is None
            or normalized_expected.project_id == normalized_stored.project_id,
            normalized_expected.tenant_id is None
            or normalized_expected.tenant_id == normalized_stored.tenant_id,
            normalized_expected.session_id is None
            or normalized_expected.session_id == normalized_stored.session_id,
            normalized_expected.agent_name is None
            or normalized_expected.agent_name == normalized_stored.agent_name,
            normalized_expected.usecase is None
            or normalized_expected.usecase == normalized_stored.usecase,
            normalized_expected.source_id is None
            or normalized_expected.source_id == normalized_stored.source_id,
            normalized_expected.document_id is None
            or normalized_expected.document_id == normalized_stored.document_id,
            not normalized_expected.tags
            or all(tag in normalized_stored.tags for tag in normalized_expected.tags),
        )
    )


def build_config() -> FakeConfigurationView:
    values = build_project_scope_config(
        usecase_name="architecture_document_qa",
        agent_name="architecture_document_agent",
        strategy_name="retrieval_augmented",
        strategy_type="retrieval_augmented",
        usecase_allowed_project_ids=("arch_docs",),
        usecase_default_project_id="arch_docs",
        agent_allowed_project_ids=("arch_docs",),
        agent_default_project_id="arch_docs",
    )
    values["app"] = {"active_usecase": "architecture_document_qa"}
    values["orchestration"]["enabled"] = True
    values["orchestration"]["defaults"].update(
        {
            "max_steps": 8,
            "max_tool_calls": 4,
            "max_memory_searches": 3,
            "max_llm_calls": 6,
            "max_turn_duration_seconds": 120,
            "max_stream_duration_seconds": 300,
        }
    )
    values["orchestration"]["strategies"]["retrieval_augmented"].update(
        {
            "enabled": True,
            "allowed_usecases": ["architecture_document_qa"],
            "llm_profile": "retrieval_profile",
            "memory_enabled": True,
            "memory_write_enabled": False,
            "tools_enabled": False,
            "memory": {
                "default_limit": 4,
                "include_document_chunks": True,
                "include_user_memory": True,
            },
        }
    )
    values["orchestration"]["usecases"]["architecture_document_qa"].update(
        {
            "llm_profile": "retrieval_profile",
            "allowed_strategies": ["retrieval_augmented"],
            "tools": {"enabled": False, "allowed_tools": []},
        }
    )
    values["agents"]["defaults"] = {
        "enabled": True,
        "stream_llm_deltas": True,
        "expose_agent_metadata": True,
        "known_prompt_profiles": ["document_qa_v1"],
    }
    values["agents"]["plugins"]["architecture_document_agent"].update(
        {
            "type": "document_qa",
            "llm_profile": "retrieval_profile",
            "prompt_profile": "document_qa_v1",
            "capabilities": {
                "answer": True,
                "review": False,
                "stream": True,
                "memory_read": True,
                "memory_write": False,
                "memory_candidate_extract": False,
                "tool_intents": False,
                "tool_execute": False,
                "self_managed_memory": False,
                "self_managed_tools": False,
            },
            "context_policy": {
                "require_context_for_grounded_claims": True,
                "cite_context_labels": True,
                "max_context_items": 6,
                "max_context_bytes": 12000,
                "allow_untrusted_context_instructions": False,
            },
            "allowed_memory_scopes": ["project", "usecase"],
        }
    )
    values["llm"] = {"defaults": {"profile": "retrieval_profile"}}
    values["memory"] = {"enabled": True}
    values["observability"] = {
        "trace_enabled": True,
        "trace_payloads_enabled": True,
        "trace_store_required": True,
        "redact_secrets": True,
        "max_trace_payload_chars": 8000,
    }
    return FakeConfigurationView(values)


def build_memory_gateway(adapter: FakeMemoryAdapter) -> DefaultMemoryGateway:
    settings = build_memory_settings(enabled=True, default_scope="project", limit_max=8)
    return DefaultMemoryGateway(settings=settings, adapter=adapter)


def build_runtime(*, memory_gateway: DefaultMemoryGateway) -> DefaultOrchestrationRuntime:
    config = build_config()
    return DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="retrieved runtime answer"),
        memory=memory_gateway,
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )


def build_record(*, memory_id: str, project_id: str, text: str) -> MemoryResult:
    return MemoryResult.from_record(
        MemoryRecord(
            memory_id=memory_id,
            text=text,
            memory_type="document_chunk",
            scope=MemoryScope(project_id=project_id),
            source={"source_id": f"{memory_id}.md", "document_id": f"{memory_id}.md"},
            title=f"{project_id} chunk",
        ),
        score=0.95,
    )


@pytest.mark.asyncio
async def test_retrieval_runtime_defaults_to_arch_docs_scope() -> None:
    adapter = ScopeAwareFakeMemoryAdapter(
        results=MemorySearchResult(
            results=[
                build_record(
                    memory_id="memory-arch",
                    project_id="arch_docs",
                    text="Architecture guidance for the backend memory scope.",
                ),
                build_record(
                    memory_id="memory-design",
                    project_id="design_docs",
                    text="Design guidance that should stay out of arch_docs retrieval.",
                ),
            ]
        )
    )
    runtime = build_runtime(memory_gateway=build_memory_gateway(adapter))

    session_id = "session_retrieval_project_scope"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_retrieval_project_scope",
        user_id="user_1",
        message="Summarize the architecture memory scope",
        usecase="architecture_document_qa",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_retrieval_project_scope",
        trace_id="trace_retrieval_project_scope",
        session_id=session_id,
        user_id="user_1",
        project_id=None,
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "retrieved runtime answer"
    assert result.memory_searches[0].result_count == 1
    assert adapter.search_requests[0].scope.project_id == "arch_docs"
    assert adapter.search_requests[0].scope.user_id is None
    assert adapter.search_requests[0].scope.session_id is None
    assert adapter.search_requests[0].scope.agent_name is None
    assert adapter.search_requests[0].scope.usecase is None


@pytest.mark.asyncio
async def test_retrieval_runtime_rejects_project_outside_arch_docs_scope() -> None:
    adapter = ScopeAwareFakeMemoryAdapter(
        results=MemorySearchResult(
            results=[
                build_record(
                    memory_id="memory-arch",
                    project_id="arch_docs",
                    text="Architecture guidance for the backend memory scope.",
                )
            ]
        )
    )
    runtime = build_runtime(memory_gateway=build_memory_gateway(adapter))

    session_id = "session_retrieval_out_of_scope"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_retrieval_out_of_scope",
        user_id="user_1",
        message="Summarize the architecture memory scope",
        usecase="architecture_document_qa",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_retrieval_out_of_scope",
        trace_id="trace_retrieval_out_of_scope",
        session_id=session_id,
        user_id="user_1",
        project_id="design_docs",
    )

    with pytest.raises(OrchestrationDependencyUnavailableError):
        await runtime.run_turn(request=request, context=context)

    assert adapter.search_requests == []