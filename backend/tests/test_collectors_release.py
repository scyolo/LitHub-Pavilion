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

def test_openalex_repository_copy_is_not_publisher_evidence():
    from app.collectors.openalex import work_to_raw_paper
    work = {'id': 'https://openalex.org/W1', 'title': 'Test publication', 'publication_year': 2024, 'doi': 'https://doi.org/10.48550/arxiv.2301.12345', 'locations': [{'source': {'id': 'https://openalex.org/S123'}, 'is_published': False, 'landing_page_url': 'https://arxiv.org/abs/2301.12345'}]}
    assert work_to_raw_paper(work, 'https://example.org', source_id='S123')[1] is None
    work['locations'].append({'source': {'id': 'https://openalex.org/S123'}, 'is_published': True, 'landing_page_url': 'https://doi.org/10.5555/published'})
    _, raw = work_to_raw_paper(work, 'https://example.org', source_id='S123')
    assert raw and raw.doi == '10.5555/published' and raw.arxiv_id == '2301.12345'
    assert work_to_raw_paper(work, 'https://example.org', source_id='S124')[1] is None


@pytest.mark.asyncio
async def test_joint_ecai_edition_does_not_collect_a_second_b_level_copy():
    from app.collectors.editions import joint_edition
    from app.services.pipeline import CrawlPipeline

    pipeline = CrawlPipeline(None)
    papers, incomplete = await pipeline._collect_unit_async(None, SimpleNamespace(abbr='ECAI'), 2026, True)
    assert papers == [] and incomplete is True
    assert 'IJCAI' in pipeline._collection_issue
    assert joint_edition('ECAI', 2025) is None
    assert joint_edition('ECAI', 2027) is None
    assert joint_edition('IJCAI', 2026) is None


@pytest.mark.asyncio
async def test_official_inventory_precedes_available_dblp(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services import pipeline as module

    from app.collectors.dblp import RawPaper
    record = RawPaper(source='manual', venue_key='https://openaccess.thecvf.com/content/CVPR2025/html/verified.html', title='Verified paper', authors=['Lovelace, Ada'], year=2025)
    official = AsyncMock(return_value=[record])
    dblp = AsyncMock(side_effect=AssertionError("DBLP must not short-circuit the publisher"))
    monkeypatch.setattr(module, "fetch_official_inventory", official)
    monkeypatch.setattr(module, "fetch_toc", dblp)
    pipeline = module.CrawlPipeline(None)
    venue = SimpleNamespace(abbr="CVPR", type="conf", dblp_toc_pattern="cvpr{year}")
    papers, incomplete = await pipeline._collect_unit_async(None, venue, 2025, True)
    assert papers == [record] and incomplete is False
    official.assert_awaited_once()
    dblp.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("official_error", [False, True])
async def test_dblp_only_inventory_stays_retryable(monkeypatch, official_error):
    from unittest.mock import AsyncMock
    from app.services import pipeline as module

    official = AsyncMock(side_effect=ValueError("unavailable")) if official_error else AsyncMock(return_value=None)
    monkeypatch.setattr(module, "fetch_official_inventory", official)
    monkeypatch.setattr(module, "fetch_toc", AsyncMock(return_value=["indexed-paper"]))
    monkeypatch.setattr(module, "fetch_configured_inventory", AsyncMock(return_value=[]))
    pipeline = module.CrawlPipeline(None)
    pipeline._openalex_paused_until = float("inf")
    venue = SimpleNamespace(abbr="ICRA", type="conf", dblp_toc_pattern="icra{year}",
                            dblp_stream="conf/icra", openalex_source_id=None, issn=None, s2_venue=None)
    papers, incomplete = await pipeline._collect_unit_async(None, venue, 2025, True)
    assert papers == ["indexed-paper"] and incomplete is True
    assert "DBLP index exhausted" in pipeline._collection_issue
