"""S2 batch 语义测试：全未知 ID → 全 None（S2 的 400 "No valid paper ids"），混合 → 逐位对齐。"""
import httpx
import pytest

from app.collectors.s2 import enrich_batch
from app.ratelimit import AsyncTokenBucket


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_all_unknown_ids_return_nones_not_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "No valid paper ids given"})

    async with _client(handler) as client:
        result = await enrich_batch(client, AsyncTokenBucket(10), ["DOI:10.1/x", "DBLP:conf/x/y"], "")
    assert result == [None, None]


@pytest.mark.asyncio
async def test_mixed_ids_align_positionally():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert b"ArXiv:1706.03762" in body
        return httpx.Response(
            200,
            json=[None, {"paperId": "abc", "title": "Attention", "externalIds": {"ArXiv": "1706.03762"}, "citationCount": 1, "authors": []}],
        )

    async with _client(handler) as client:
        result = await enrich_batch(
            client, AsyncTokenBucket(10), ["DOI:10.9999/unknown", "ArXiv:1706.03762"], ""
        )
    assert result[0] is None
    assert result[1].title == "Attention"
    assert result[1].arxiv_id == "1706.03762"
