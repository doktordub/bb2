"""Memory gateway contracts and normalized memory payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext


@dataclass(slots=True)
class MemoryScope:
    """Logical scope applied to memory reads and writes."""

    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    usecase: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemorySearchRequest:
    """Normalized request for memory retrieval."""

    text: str
    scope: MemoryScope
    memory_types: list[str] | None = None
    limit: int = 10
    include_document_chunks: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryResult:
    """Single logical memory result."""

    memory_id: str
    text: str
    score: float | None = None
    memory_type: str | None = None
    source_id: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryWrite:
    """Normalized write request for long-term memory."""

    text: str
    scope: MemoryScope
    memory_type: str
    stable_key: str | None = None
    importance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRecord:
    """Persisted memory record returned by the gateway."""

    memory_id: str
    text: str
    memory_type: str
    scope: MemoryScope
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryGateway(Protocol):
    """Provider-neutral memory access used by orchestration code."""

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        ...

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
        ...

    async def forget(self, memory_id: str, context: OrchestrationContext) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...