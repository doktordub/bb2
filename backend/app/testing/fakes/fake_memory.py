"""In-memory fake memory gateway for contract-focused tests."""

from __future__ import annotations

from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.memory import (
    MemoryRecord,
    MemoryResult,
    MemorySearchRequest,
    MemoryWrite,
)


class FakeMemoryGateway:
    """Deterministic memory fake that records reads and writes."""

    def __init__(
        self,
        results: list[MemoryResult] | None = None,
        *,
        search_error: Exception | None = None,
        upsert_error: Exception | None = None,
        forget_error: Exception | None = None,
        health_payload: dict[str, Any] | None = None,
        health_error: Exception | None = None,
    ) -> None:
        self.results = list(results or [])
        self.records: dict[str, MemoryRecord] = {}
        self.search_requests: list[MemorySearchRequest] = []
        self.writes: list[MemoryWrite] = []
        self.forgotten_ids: list[str] = []
        self.contexts: list[OrchestrationContext] = []
        self._search_error = search_error
        self._upsert_error = upsert_error
        self._forget_error = forget_error
        self._health_payload = health_payload or {"status": "ok", "provider": "fake"}
        self._health_error = health_error

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        if self._search_error is not None:
            raise self._search_error
        self.search_requests.append(request)
        self.contexts.append(context)
        return list(self.results)

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
        if self._upsert_error is not None:
            raise self._upsert_error
        self.writes.append(memory)
        self.contexts.append(context)
        memory_id = memory.stable_key or f"fake_memory_{len(self.writes)}"
        record = MemoryRecord(
            memory_id=memory_id,
            text=memory.text,
            memory_type=memory.memory_type,
            scope=memory.scope,
            metadata=dict(memory.metadata),
        )
        self.records[memory_id] = record
        return record

    async def forget(self, memory_id: str, context: OrchestrationContext) -> None:
        if self._forget_error is not None:
            raise self._forget_error
        self.forgotten_ids.append(memory_id)
        self.contexts.append(context)
        self.records.pop(memory_id, None)

    async def health(self) -> dict[str, Any]:
        if self._health_error is not None:
            raise self._health_error
        return dict(self._health_payload)