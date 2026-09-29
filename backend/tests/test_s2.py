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


@pytest.mark.asyncio
async def test_bulk_fetches_unfiltered_inventory_until_token_and_filters_stream(monkeypatch):
    from contextlib import asynccontextmanager
    from app.collectors import s2 as module
    from app.models import Venue

    requests = []
    page1 = {
        "data": [
            {"title": "Formal paper", "year": 2025, "publicationDate": "2026-09-22",
             "externalIds": {"DBLP": "conf/aaai/Formal25", "ArXiv": "2501.12345"},
             "authors": [], "citationCount": 1},
            {"title": "arXiv only", "year": 2025, "externalIds": {"DBLP": "journals/corr/abs-2501"},
             "authors": [], "citationCount": 0},
        ],
        "token": "next-page",
    }
    page2 = {
        "data": [{"title": "Second formal paper", "year": 2025,
                   "externalIds": {"DBLP": "conf/aaai/Formal26"}, "authors": [], "citationCount": 2}],
    }

    def handler(request):
        requests.append(request)
        if request.url.params.get("token"):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    @asynccontextmanager
    async def client_factory():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yield client

    monkeypatch.setattr(module, "_make_client", client_factory)
    venue = Venue(abbr="AAAI", name="AAAI", dblp_stream="conf/aaai", s2_venue="AAAI",
                  type="conf", ccf_level="A")
    rows = await module.fetch_bulk_raw_papers(venue, 2025, ["language model"], "", 1000, max_pages_per_query=3)

    assert [row.venue_key for row in rows] == ["conf/aaai/Formal25", "conf/aaai/Formal26"]
    assert rows[0].publication_date is None
    assert "query" not in requests[0].url.params
    assert requests[1].url.params["token"] == "next-page"


@pytest.mark.asyncio
async def test_bulk_fetch_rejects_repeated_token(monkeypatch):
    from contextlib import asynccontextmanager
    from app.collectors import s2 as module
    from app.collectors.s2 import S2BulkCoverageIncomplete
    from app.models import Venue

    def handler(_request):
        return httpx.Response(200, json={"data": [], "token": "same"})

    @asynccontextmanager
    async def client_factory():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yield client

    monkeypatch.setattr(module, "_make_client", client_factory)
    venue = Venue(abbr="AAAI", name="AAAI", dblp_stream="conf/aaai", s2_venue="AAAI",
                  type="conf", ccf_level="A")
    with pytest.raises(S2BulkCoverageIncomplete):
        await module.fetch_bulk_raw_papers(venue, 2025, [], "", 1000, max_pages_per_query=3)
