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

    def __init__(self, results: list[MemoryResult] | None = None) -> None:
        self.results = list(results or [])
        self.records: dict[str, MemoryRecord] = {}
        self.search_requests: list[MemorySearchRequest] = []
        self.writes: list[MemoryWrite] = []
        self.forgotten_ids: list[str] = []
        self.contexts: list[OrchestrationContext] = []

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        self.search_requests.append(request)
        self.contexts.append(context)
        return list(self.results)

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
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
        self.forgotten_ids.append(memory_id)
        self.contexts.append(context)
        self.records.pop(memory_id, None)

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "fake"}