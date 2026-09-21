"""Small collectors regression fixtures; no live API calls."""
from types import SimpleNamespace

import httpx
import pytest

from app.collectors.openalex import OpenAlexBudgetExhausted, fetch_works_by_source, resolve_source_id
from app.collectors.s2 import enrich_batch, fetch_bulk_raw_papers
from app.ratelimit import AsyncTokenBucket


@pytest.mark.asyncio
async def test_s2_does_not_retry_permanent_validation_errors():
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "bad field"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await enrich_batch(client, AsyncTokenBucket(1000), ["ArXiv:2501.10040"], "")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_s2_rejects_misaligned_batch_responses():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))) as client:
        with pytest.raises(ValueError, match="aligned"):
            await enrich_batch(client, AsyncTokenBucket(1000), ["ArXiv:2501.10040"], "")


@pytest.mark.asyncio
async def test_bulk_uses_upstream_year_not_a_forced_query_year(monkeypatch):
    import app.collectors.s2 as source

    async def page(*args):
        return {"data": [
            {"title": "Wrong year", "year": 2024, "externalIds": {"DBLP": "conf/nips/Wrong24"}},
            {"title": "Valid year", "year": 2025, "externalIds": {"DBLP": "conf/nips/Valid25"}},
        ]}
    monkeypatch.setattr(source, "bulk_search_venue_year", page)
    venue = SimpleNamespace(s2_venue="NeurIPS", dblp_stream="conf/nips")
    papers = await fetch_bulk_raw_papers(venue, 2025, ["inference"], "", 1)
    assert len(papers) == 1
    assert papers[0].year == 2025
    assert papers[0].extra["provenance"] == "s2_bulk"


@pytest.mark.asyncio
async def test_openalex_repeated_cursor_terminates():
    payload = {"results": [{"id": "W1"}], "meta": {"next_cursor": "repeat"}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ValueError, match="pagination"):
            await fetch_works_by_source(client, AsyncTokenBucket(1000), "", "S123", [2025])


@pytest.mark.asyncio
async def test_source_lookup_uses_same_budget_error_as_work_lookup():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429, json={}))) as client:
        with pytest.raises(OpenAlexBudgetExhausted):
            await resolve_source_id(client, AsyncTokenBucket(1000), "ICLR", "")


def test_retagging_preserves_rule_row_identity(db, sample_paper, sample_direction):
    from app.models import PaperDirection
    from app.services.tagging import apply_tagging

    row = PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, source="rule", score=1)
    db.add(row)
    db.commit()
    created = row.created_at
    apply_tagging(db, sample_paper.id, "Speculative decoding", None,
                  [(sample_direction.id, "speculative decoding", 1.0, "title")], {sample_direction.id: 2})
    db.commit()
    assert db.get(PaperDirection, (sample_paper.id, sample_direction.id)).created_at == created
    assert db.get(PaperDirection, (sample_paper.id, sample_direction.id)).score == 2
