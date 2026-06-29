"""Composition helpers for backend long-term memory services."""

from __future__ import annotations

from typing import cast

from app.config.view import get_memory_settings
from app.contracts.config import ConfigurationView
from app.contracts.memory import MemoryGateway
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.memory.errors import MemoryAdapterError, MemoryConfigurationError
from app.memory.gateway import DefaultMemoryGateway, UnavailableMemoryGateway
from app.persistence.settings import MemoryPersistenceSettings


async def build_memory_gateway(
    config: ConfigurationView,
    settings: MemoryPersistenceSettings,
) -> MemoryGateway:
    """Build the configured memory gateway for backend startup."""

    memory_settings = get_memory_settings(config)

    if settings.provider in {"", "disabled", "none"}:
        return cast(
            MemoryGateway,
            UnavailableMemoryGateway(
                provider=settings.provider or "disabled",
                required=settings.required,
                reason="disabled",
            ),
        )

    if settings.provider == "fake":
        return cast(
            MemoryGateway,
            DefaultMemoryGateway(
                settings=memory_settings,
                adapter=FakeMemoryAdapter(),
            ),
        )

    if settings.provider == "memory_store":
        adapter = MemoryStoreAdapter(settings.memory_store, required=settings.required)
        if settings.required:
            try:
                await adapter.initialize()
            except Exception as exc:
                raise MemoryAdapterError("Memory gateway initialization failed.") from exc
        return cast(
            MemoryGateway,
            DefaultMemoryGateway(
                settings=memory_settings,
                adapter=adapter,
            ),
        )

    raise MemoryConfigurationError(
        f"Unsupported memory gateway provider: {settings.provider}"
    )