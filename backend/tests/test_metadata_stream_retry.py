import asyncio

import httpcore
import httpx
import pytest

from app.collectors.crossref import request_with_retry


def test_partial_metadata_stream_retries_without_accepting_incomplete_body(monkeypatch):
    attempts = []

    class Client:
        async def get(self, url, params=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise httpcore.RemoteProtocolError("incomplete body")
            return httpx.Response(200, json={"message": {"items": []}})

    async def no_wait(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    result = asyncio.run(
        request_with_retry(Client(), "https://api.crossref.org/works", attempts=2)
    )
    assert len(attempts) == 2 and result.json() == {"message": {"items": []}}

    class Broken:
        async def get(self, url, params=None):
            raise httpcore.RemoteProtocolError("incomplete body")

    with pytest.raises(httpx.RemoteProtocolError):
        asyncio.run(
            request_with_retry(Broken(), "https://api.crossref.org/works", attempts=1)
        )
