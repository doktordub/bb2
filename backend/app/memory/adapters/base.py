"""Internal adapter protocol for gateway-owned memory operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.contracts.memory import (
    DocumentIngestRequest,
    DocumentIngestResult,
    MemoryChunkContextRequest,
    MemoryChunkContextResult,
    MemoryDeleteByScopeRequest,
    MemoryDeleteResult,
    MemoryExportByScopeRequest,
    MemoryExportResult,
    MemoryForgetRequest,
    MemoryGetRequest,
    MemoryHealthResult,
    MemoryLifecycleRequest,
    MemoryRecord,
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatsResult,
    MemorySupersedeRequest,
    MemoryContradictRequest,
    MemoryWrite,
    MemoryWriteResult,
)


class MemoryAdapter(Protocol):
    """Gateway-internal adapter surface without orchestration context arguments."""

    async def initialize(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        ...

    async def get(self, request: MemoryGetRequest) -> MemoryRecord | None:
        ...

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
    ) -> MemoryChunkContextResult | None:
        ...

    async def upsert(self, memory: MemoryWrite) -> MemoryWriteResult:
        ...

    async def promote(self, request: MemoryLifecycleRequest) -> MemoryWriteResult:
        ...

    async def supersede(self, request: MemorySupersedeRequest) -> MemoryWriteResult:
        ...

    async def contradict(self, request: MemoryContradictRequest) -> MemoryWriteResult:
        ...

    async def expire(self, request: MemoryLifecycleRequest) -> MemoryWriteResult:
        ...

    async def forget(self, request: MemoryForgetRequest) -> MemoryWriteResult:
        ...

    async def ingest_document(
        self,
        request: DocumentIngestRequest,
    ) -> DocumentIngestResult:
        ...

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
    ) -> MemoryDeleteResult:
        ...

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
    ) -> MemoryExportResult:
        ...

    async def health(self) -> MemoryHealthResult | Mapping[str, Any]:
        ...

    async def stats(self, scopes: MemoryScope | None = None) -> MemoryStatsResult:
        ...