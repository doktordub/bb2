import pytest

from app.services.http_client import HttpClientFactory


@pytest.mark.asyncio
async def test_http_client_factory_applies_timeout_and_headers() -> None:
    factory = HttpClientFactory(
        timeout_seconds=12,
        default_headers={"X-Test-Header": "enabled"},
    )

    async with factory.create_client() as client:
        assert client.timeout.connect == 12
        assert client.headers["X-Test-Header"] == "enabled"