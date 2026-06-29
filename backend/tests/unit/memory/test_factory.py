from __future__ import annotations

import pytest

from app.contracts.health import HEALTH_NOT_CONFIGURED
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.memory.errors import MemoryConfigurationError
from app.memory.factory import build_memory_gateway
from app.memory.gateway import DefaultMemoryGateway, UnavailableMemoryGateway
from app.persistence.settings import MemoryPersistenceSettings, MemoryStoreSettings
from app.testing.fakes import FakeConfigurationView


def build_settings(
    provider: str,
    *,
    required: bool = False,
    config_path=None,
    database_path=None,
) -> MemoryPersistenceSettings:
    return MemoryPersistenceSettings(
        provider=provider,
        required=required,
        memory_store=MemoryStoreSettings(
            config_path=config_path,
            database_path=database_path,
        ),
    )


def build_config(provider: str, *, enabled: bool = True) -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "memory": {
                "enabled": enabled,
                "provider": provider,
                "required": False,
            },
            "features": {"memory_enabled": enabled},
        }
    )


async def test_build_memory_gateway_returns_unavailable_gateway_for_disabled_provider() -> None:
    gateway = await build_memory_gateway(
        build_config("disabled", enabled=False),
        build_settings("disabled"),
    )

    assert isinstance(gateway, UnavailableMemoryGateway)
    health = await gateway.health()
    stats = await gateway.stats()

    assert health["status"] == HEALTH_NOT_CONFIGURED
    assert health["enabled"] is False
    assert stats.configured is False


async def test_build_memory_gateway_returns_fake_gateway_for_fake_provider() -> None:
    gateway = await build_memory_gateway(build_config("fake"), build_settings("fake"))

    assert isinstance(gateway, DefaultMemoryGateway)
    assert isinstance(gateway._adapter, FakeMemoryAdapter)
    health = await gateway.health()
    assert health.provider == "fake"


async def test_build_memory_gateway_returns_lazy_memory_store_adapter(tmp_path) -> None:
    gateway = await build_memory_gateway(
        build_config("memory_store"),
        build_settings("memory_store", database_path=tmp_path / "memory-store"),
    )

    assert isinstance(gateway, DefaultMemoryGateway)
    assert isinstance(gateway._adapter, MemoryStoreAdapter)
    health = await gateway.health()
    assert health["provider"] == "memory_store"
    assert health["service_initialized"] is False


async def test_build_memory_gateway_rejects_unknown_provider() -> None:
    with pytest.raises(MemoryConfigurationError):
        await build_memory_gateway(
            build_config("unsupported"),
            build_settings("unsupported"),
        )