from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.contracts.health import HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_OK
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.persistence.settings import MemoryStoreSettings


@pytest.mark.asyncio
async def test_memory_store_adapter_health_reports_missing_config_path_for_optional_store(
    tmp_path,
) -> None:
    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=tmp_path / "missing-memory-store.yaml",
            database_path=None,
            default_scope="project",
            search_limit_default=10,
            search_limit_max=30,
            allow_writes=False,
        ),
        required=False,
    )

    health = await adapter.health()

    assert health["status"] == HEALTH_DEGRADED
    assert health["configured"] is True
    assert health["provider"] == "memory_store"
    assert health["required"] is False
    assert health["enabled"] is True
    assert health["search_available"] is False
    assert health["ingest_available"] is False
    assert health["reason"] == "config_path_missing"
    assert health["error"] == "config_path_missing"
    assert health["error_type"] == "FileNotFoundError"


@pytest.mark.asyncio
async def test_memory_store_adapter_health_returns_ok_without_exposing_database_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeMemoryService:
        @classmethod
        def from_config(cls, config_path: object = None, **overrides: object) -> FakeMemoryService:
            return cls()

        def health(self) -> object:
            return SimpleNamespace(
                database_path=tmp_path / "should-not-leak",
                schema_version=3,
                dependencies={"arcadedb_embedded": True, "fastembed": False},
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=object,
            MemorySearchQuery=object,
            MemoryService=FakeMemoryService,
            Scope=object,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store",
            default_scope="user",
            search_limit_default=10,
            search_limit_max=30,
            allow_writes=False,
            embedding_dimension=384,
        ),
        required=True,
    )
    await adapter.initialize()

    health = await adapter.health()
    await adapter.close()

    assert health["status"] == HEALTH_OK
    assert health["enabled"] is True
    assert health["embedding_model_configured"] is True
    assert health["embedding_dimension"] == 384
    assert health["search_available"] is True
    assert health["ingest_available"] is True
    assert health["schema_initialized"] is True
    assert health["dependency_available"] is True
    assert health["dependencies"] == {"arcadedb_embedded": True, "fastembed": False}
    assert health["schema_version"] == 3
    assert "database_path" not in health


@pytest.mark.asyncio
async def test_memory_store_adapter_health_marks_required_problem_as_failed(
    tmp_path,
) -> None:
    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=tmp_path / "missing-memory-store.yaml",
            database_path=None,
            default_scope="project",
            search_limit_default=10,
            search_limit_max=30,
            allow_writes=False,
        ),
        required=True,
    )

    health = await adapter.health()

    assert health["status"] == HEALTH_FAILED