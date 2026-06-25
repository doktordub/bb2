from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.memory import MemoryResult, MemoryScope, MemorySearchRequest
from app.persistence.memory_store_adapter import MemoryStoreAdapter, normalize_memory_search_limit
from app.persistence.settings import MemoryStoreSettings
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_context(*, project_id: str | None = None) -> OrchestrationContext:
    metadata = {"project_id": project_id} if project_id is not None else {}
    return OrchestrationContext(
        request=RequestContext(
            user_id="user-123",
            session_id="session-123",
            message="remember this",
            usecase="support",
            trace_id="trace-123",
            metadata=metadata,
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView({}),
        runtime_metadata={},
    )


def test_memory_scope_normalizes_strings_and_summarizes_without_identifiers() -> None:
    scope = MemoryScope(
        user_id=" user-1 ",
        project_id=" ",
        tenant_id=" tenant-1 ",
        session_id=" session-1 ",
        metadata={"kind": "test"},
    )

    normalized = scope.normalized()

    assert normalized.user_id == "user-1"
    assert normalized.project_id is None
    assert normalized.tenant_id == "tenant-1"
    assert normalized.session_id == "session-1"
    assert normalized.has_explicit_scope() is True
    assert normalized.summary() == {
        "scope_type": "user",
        "user_id_present": True,
        "project_id_present": False,
        "tenant_id_present": True,
        "usecase_present": False,
        "session_id_present": True,
    }


def test_normalize_memory_search_limit_uses_defaults_and_caps_maximum() -> None:
    assert normalize_memory_search_limit(None, default_limit=8, max_limit=20) == 8
    assert normalize_memory_search_limit(0, default_limit=8, max_limit=20) == 8
    assert normalize_memory_search_limit(50, default_limit=8, max_limit=20) == 20
    assert normalize_memory_search_limit(3, default_limit=8, max_limit=20) == 3


@pytest.mark.asyncio
async def test_memory_store_adapter_search_uses_default_user_scope_caps_limit_and_emits_safe_traces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    created_services: list[FakeMemoryService] = []

    class FakeMemorySearchQuery:
        def __init__(self, **kwargs: object) -> None:
            self.text = kwargs["text"]
            self.scope = kwargs["scope"]
            self.limit = kwargs["limit"]
            self.memory_types = kwargs.get("memory_types")
            self.allow_retrieval_only = kwargs["allow_retrieval_only"]

    class FakeScope:
        def __init__(self, *, user_id: str | None = None, project_id: str | None = None) -> None:
            self.user_id = user_id
            self.project_id = project_id

    class FakeMemoryCreate:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class FakeMemoryService:
        def __init__(self, *, config_path: object, overrides: dict[str, object]) -> None:
            self.config_path = config_path
            self.overrides = overrides
            self.search_calls: list[FakeMemorySearchQuery] = []
            self.closed = False

        @classmethod
        def from_config(cls, config_path: object = None, **overrides: object) -> FakeMemoryService:
            service = cls(config_path=config_path, overrides=dict(overrides))
            created_services.append(service)
            return service

        def search(self, query: FakeMemorySearchQuery) -> list[object]:
            self.search_calls.append(query)
            record = SimpleNamespace(
                memory_id="memory-1",
                text="safe text",
                memory_type="project_fact",
                metadata={"source": "fake"},
                source_hash="source-1",
                chunk_id=None,
            )
            return [SimpleNamespace(memory=record, final_score=0.75)]

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=FakeMemoryCreate,
            MemorySearchQuery=FakeMemorySearchQuery,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store",
            default_scope="user",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )
    context = build_context()
    request = MemorySearchRequest(
        text="top secret query",
        scope=MemoryScope(session_id="session-123"),
        include_document_chunks=False,
        limit=50,
    )

    results = await adapter.search(request, context)
    await adapter.close()

    assert results == [
        MemoryResult(
            memory_id="memory-1",
            text="safe text",
            score=0.75,
            memory_type="project_fact",
            source_id="source-1",
            chunk_id=None,
            metadata={"source": "fake"},
        )
    ]
    assert len(created_services) == 1
    assert created_services[0].overrides == {"database": {"path": str(tmp_path / "memory-store")}}
    assert len(created_services[0].search_calls) == 1
    query = created_services[0].search_calls[0]
    assert query.scope.user_id == "user-123"
    assert query.scope.project_id is None
    assert query.limit == 20
    assert query.memory_types == [
        "user_preference",
        "project_fact",
        "task_state",
        "conversation_summary",
        "decision",
        "observation",
        "error_debug_note",
    ]
    assert created_services[0].closed is True

    trace_events = context.trace.events
    assert [event.event_type for event in trace_events] == [
        "memory_search_started",
        "memory_search_completed",
    ]
    assert all("top secret query" not in str(event.payload) for event in trace_events)
    assert trace_events[0].payload == {
        "scope_type": "user",
        "user_id_present": True,
        "project_id_present": False,
        "tenant_id_present": False,
        "usecase_present": False,
        "session_id_present": True,
        "limit": 20,
        "include_document_chunks": False,
        "memory_type_count": 7,
    }
    assert trace_events[1].payload == {
        "scope_type": "user",
        "user_id_present": True,
        "project_id_present": False,
        "tenant_id_present": False,
        "usecase_present": False,
        "session_id_present": True,
        "limit": 20,
        "result_count": 1,
        "success": True,
    }