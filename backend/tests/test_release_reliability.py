"""Release-critical regressions; all I/O uses temporary data and mocked networks."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.collectors.dblp import ProbeResult, RawPaper, fetch_toc, probe_dblp
from app.config import settings
from app.models import CrawlLog, CrawlState, Paper
from app.ratelimit import AsyncTokenBucket
from app.services.pipeline import CrawlPipeline


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("fail", "failed"), ("empty", "partial")])
async def test_incomplete_collection_never_commits_checkpoint(session_factory, sample_venue, monkeypatch, mode, expected):
    pipeline = CrawlPipeline(session_factory)
    monkeypatch.setattr(pipeline, "_probe", AsyncMock(return_value=ProbeResult(False, "offline")))
    collector = AsyncMock(side_effect=RuntimeError("upstream unavailable")) if mode == "fail" else AsyncMock(return_value=([], True))
    monkeypatch.setattr(pipeline, "_collect_unit_async", collector)
    assert await pipeline.submit_backfill(years=[2025], run_id="test-incomplete")
    await pipeline.wait_idle()
    with session_factory() as session:
        run = session.query(CrawlLog).filter(CrawlLog.run_id == "test-incomplete", CrawlLog.venue_id.is_(None)).one()
        assert run.status == expected
        assert run.finished_at is not None
        assert session.query(CrawlState).count() == 0
    assert not pipeline.status.running
    assert pipeline.status.current is None


@pytest.mark.asyncio
async def test_one_failed_unit_makes_run_partial(session_factory, sample_venue, monkeypatch):
    pipeline = CrawlPipeline(session_factory)
    monkeypatch.setattr(pipeline, "_probe", AsyncMock(return_value=ProbeResult(True, "ok")))
    raw = RawPaper(source="dblp", venue_key="conf/nips/Release25", title="Reliable model inference", year=2025)
    monkeypatch.setattr(pipeline, "_collect_unit_async", AsyncMock(side_effect=[([raw], False), RuntimeError("failure")]))
    monkeypatch.setattr("app.services.pipeline.enrich_papers", AsyncMock(return_value={"enriched": 0, "failed": 0}))
    assert await pipeline.submit_backfill(years=[2025, 2026], run_id="test-partial")
    await pipeline.wait_idle()
    with session_factory() as session:
        run = session.query(CrawlLog).filter(CrawlLog.run_id == "test-partial", CrawlLog.venue_id.is_(None)).one()
        assert run.status == "partial"
        assert session.query(CrawlState).count() == 1
        assert session.query(Paper).count() == 1


@pytest.mark.asyncio
async def test_duplicate_submission_and_shutdown_are_safe(session_factory, monkeypatch):
    pipeline = CrawlPipeline(session_factory)
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(pipeline, "_run", blocked)
    assert await pipeline.submit_weekly(run_id="first")
    await entered.wait()
    assert pipeline.status.run_id == "first"
    assert not await pipeline.submit_weekly(run_id="second")
    await pipeline.shutdown()
    assert pipeline.status.running is False
    assert pipeline.status.current is None
    assert pipeline.status.progress is None


@pytest.mark.asyncio
async def test_links_backfill_preserves_local_archive(session_factory, sample_paper, tmp_path, monkeypatch):
    from app.services.links_backfill import run_links_backfill

    monkeypatch.setattr(settings, "pdf_download_enabled", False)
    monkeypatch.setattr(settings, "papers_root", tmp_path)
    archive = tmp_path / "keep.pdf"
    archive.write_bytes(b"%PDF-user-archive")
    with session_factory() as session:
        paper = session.get(Paper, sample_paper.id)
        paper.pdf_status = "downloaded"
        paper.pdf_path = "keep.pdf"
        paper.pdf_source = "arxiv"
        paper.oa_url = "https://arxiv.org/abs/2501.10040"
        session.commit()
    stats = await run_links_backfill(session_factory)
    assert archive.read_bytes() == b"%PDF-user-archive"
    assert stats.get("pdf_removed", 0) == 0
    with session_factory() as session:
        assert session.get(Paper, sample_paper.id).pdf_path == "keep.pdf"


@pytest.mark.asyncio
async def test_dblp_parses_result_envelope_and_single_author():
    payload = {"result": {"hits": {"@total": "1", "hit": [{"info": {
        "key": "conf/nips/Example25", "title": "A real paper.", "year": "2025",
        "authors": {"author": {"text": "Ada Lovelace"}},
    }}]}}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        assert (await probe_dblp(client, "https://dblp.org")).ok
        rows = await fetch_toc(client, AsyncTokenBucket(1000), "https://dblp.org", "conf/nips/nips2025")
    assert len(rows) == 1
    assert rows[0].authors
    assert rows[0].title == "A real paper"


def test_arxiv_only_create_is_link_only_and_unconfirmed(client, sample_venue):
    response = client.post("/api/papers", json={
        "title": "Arxiv-only metadata", "venue_abbr": sample_venue.abbr,
        "year": 2025, "arxiv_id": "2501.10040",
    })
    assert response.status_code == 201
    paper = client.get(response.headers["Location"]).json()
    assert paper["arxiv_id"] == "2501.10040"
    assert paper["venue_confirmed"] == 0
    assert paper["pdf_status"] == "closed"


@pytest.mark.parametrize("years", [[0], [9999], [], [2025, 2025], [2025] * 40])
def test_crawl_years_are_bounded_before_submission(client, years, monkeypatch):
    monkeypatch.setattr(CrawlPipeline, "submit_backfill", AsyncMock(return_value=True))
    response = client.post("/api/crawl/trigger", json={"scope": "backfill", "years": years})
    assert response.status_code == 400


def test_patch_directions_means_replace_not_rule_union(client, sample_paper, sample_direction, db):
    from app.models import PaperDirection

    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, score=2, source="rule"))
    db.commit()
    response = client.patch(f"/api/papers/{sample_paper.id}", json={"directions": [], "note": ""})
    assert response.status_code == 200
    assert response.json()["directions"] == []


def test_cross_site_writes_are_rejected_without_changing_data(client, sample_paper):
    response = client.delete(f"/api/papers/{sample_paper.id}", headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CROSS_SITE_WRITE"
    assert client.get(f"/api/papers/{sample_paper.id}").status_code == 200


def test_delete_does_not_follow_external_pdf_path(client, db, sample_paper, tmp_path, monkeypatch):
    root = tmp_path / "papers"
    root.mkdir()
    outside = tmp_path / "do-not-delete.pdf"
    outside.write_bytes(b"original")
    monkeypatch.setattr(settings, "papers_root", root)
    sample_paper.pdf_path = "../do-not-delete.pdf"
    db.commit()
    response = client.delete(f"/api/papers/{sample_paper.id}")
    assert response.status_code == 204
    assert outside.read_bytes() == b"original"
