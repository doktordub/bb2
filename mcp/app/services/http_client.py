"""Shared HTTP client factory for MCP services and plugins."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True, slots=True)
class HttpClientFactory:
    """Creates bounded async HTTP clients with MCP-wide defaults."""

    timeout_seconds: float
    default_headers: Mapping[str, str] = field(default_factory=dict)
    verify: bool | str = True

    @asynccontextmanager
    async def create_client(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        verify: bool | str | None = None,
    ) -> AsyncIterator[httpx.AsyncClient]:
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        timeout = httpx.Timeout(timeout_seconds or self.timeout_seconds)
        async with httpx.AsyncClient(
            headers=merged_headers,
            timeout=timeout,
            verify=self.verify if verify is None else verify,
        ) as client:
            yield client