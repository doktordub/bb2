from __future__ import annotations

import os

import pytest

from app.contracts.memory import DocumentIngestRequest, MemoryScope, MemorySearchRequest
from tests.integration.memory.support import FIXTURES_DIR, build_context, build_gateway, load_config_view


pytestmark = pytest.mark.skipif(
    os.getenv("BB2_ENABLE_REAL_MEMORY_STORE_TESTS") != "1",
    reason="local-only memory_store smoke test",
)


@pytest.mark.asyncio
async def test_real_memory_store_wrapper_can_ingest_and_search(tmp_path) -> None:
    config = await load_config_view(
        "memory_store_real_local.yaml",
        env={
            "APP_DATA_DIR": str(tmp_path),
            "MEMORY_STORE_DB_PATH": str(tmp_path / "memory-store-real-local"),
        },
    )
    gateway = await build_gateway(config)
    context = build_context(config)
    sample_path = FIXTURES_DIR / "memory" / "documents" / "backend_sample.md"

    try:
        ingest_result = await gateway.ingest_document(
            DocumentIngestRequest(
                source_id="backend-sample",
                document_id="backend-sample.md",
                scope=MemoryScope(project_id="project-1"),
                path=str(sample_path),
            ),
            context,
        )
        search_result = await gateway.search(
            MemorySearchRequest(
                text="MemoryGateway boundary",
                scope=MemoryScope(project_id="project-1"),
                include_document_chunks=True,
                limit=3,
            ),
            context,
        )

        assert ingest_result.chunks_created + ingest_result.chunks_updated >= 1
        assert search_result.results
    finally:
        if hasattr(gateway, "close"):
            await gateway.close()
