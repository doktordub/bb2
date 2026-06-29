from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.contracts.memory import MemoryExportByScopeRequest, MemoryScope
from tests.integration.memory.support import build_context, build_gateway, load_config_view


@pytest.mark.asyncio
async def test_scope_export_flows_through_gateway_and_filters_extended_backend_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_services: list[FakeMemoryService] = []

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

    def build_record(memory_id: str, *, source_id: str, text: str) -> object:
        return SimpleNamespace(
            memory_id=memory_id,
            text=text,
            memory_type="project_fact",
            scope=SimpleNamespace(
                user_id="user-1",
                project_id="project-1",
                agent_id="support_agent",
            ),
            status="active",
            metadata={
                "_backend_source": {
                    "source_id": source_id,
                    "document_id": f"doc-{source_id}",
                }
            },
            tags=["memory"],
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    class FakeMemoryService:
        def __init__(self) -> None:
            self.export_calls: list[FakeScope] = []

        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def export_scope(self, scope: FakeScope) -> object:
            self.export_calls.append(scope)
            return SimpleNamespace(
                records=[
                    build_record(
                        "memory-1",
                        source_id="source-1",
                        text="Private export record body.",
                    ),
                    build_record(
                        "memory-2",
                        source_id="source-2",
                        text="Ignore this record.",
                    ),
                ],
                exported_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

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

    config = await load_config_view("memory_store_privacy_enabled.yaml", env={})
    gateway = await build_gateway(config)
    context = build_context(config)

    result = await gateway.export_by_scope(
        MemoryExportByScopeRequest(
            scope=MemoryScope(project_id="project-1", source_id="source-1"),
            include_content=False,
        ),
        context,
    )

    assert result.record_count == 1
    assert result.records[0].source_id == "source-1"
    assert result.records[0].text == "[redacted]"
    assert created_services[0].export_calls[0].project_id == "project-1"

    if hasattr(gateway, "close"):
        await gateway.close()