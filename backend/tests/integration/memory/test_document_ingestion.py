from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.contracts.memory import DocumentIngestRequest, MemoryScope
from tests.integration.memory.support import FIXTURES_DIR, build_context, build_gateway, load_config_view


@pytest.mark.asyncio
async def test_document_ingestion_flows_through_config_factory_gateway_and_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_services: list[FakeMemoryService] = []
    sample_path = FIXTURES_DIR / "memory" / "documents" / "backend_sample.md"

    class FakeScope:
        def __init__(
            self,
            *,
            user_id: str | None = None,
            project_id: str | None = None,
            agent_id: str | None = None,
        ) -> None:
            self.user_id = user_id
            self.project_id = project_id
            self.agent_id = agent_id

    class FakeMemoryService:
        def __init__(self) -> None:
            self.ingest_calls: list[tuple[Path, FakeScope, str]] = []

        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def ingest_document(self, path: str | Path, scope: FakeScope) -> object:
            resolved_path = Path(path)
            self.ingest_calls.append((resolved_path, scope, resolved_path.read_text(encoding="utf-8")))
            return SimpleNamespace(path=resolved_path, added=3, updated=0, unchanged=0, removed=0)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=object,
            MemorySearchQuery=object,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    config = await load_config_view("memory_store_markdown_chunking.yaml", env={})
    gateway = await build_gateway(config)
    context = build_context(config)

    result = await gateway.ingest_document(
        DocumentIngestRequest(
            source_id="backend-sample",
            document_id="backend-sample.md",
            scope=MemoryScope(project_id="project-1"),
            path=str(sample_path),
        ),
        context,
    )

    assert result.chunks_created == 3
    assert result.chunks_updated == 0
    assert result.chunks_removed == 0
    assert created_services[0].ingest_calls[0][0] == sample_path
    assert "MemoryGateway" in created_services[0].ingest_calls[0][2]

    if hasattr(gateway, "close"):
        await gateway.close()