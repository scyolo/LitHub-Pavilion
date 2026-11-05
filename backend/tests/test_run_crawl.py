"""Manual crawl logging and checkpoints must preserve retryable collection states."""
import json
import sys
from pathlib import Path

import pytest

from app.models import CrawlLog, CrawlState
from scripts import run_crawl


def configure_crawl(monkeypatch, engine, outcomes):
    class Pipeline:
        def __init__(self, session_factory):
            self._collection_issue = None
            self._ingest_conflicts = False

        async def _collect_unit_async(self, session, venue, year, use_dblp):
            # The driver must not let one unit's conflict or error leak into the next.
            assert self._collection_issue is None
            assert self._ingest_conflicts is False
            outcome = outcomes[year]
            if outcome == "failed":
                self._collection_issue = "upstream unavailable"
                raise RuntimeError("upstream unavailable")
            self._collection_issue = "inventory unverified" if outcome in {"partial", "empty"} else None
            return ([] if outcome == "empty" else [year]), outcome in {"partial", "empty"}

        async def _db_call(self, function, *args):
            return function(*args)

        def _ingest_owned(self, batch, venue_id, year):
            if outcomes[year] == "conflict":
                self._ingest_conflicts = True
                self._collection_issue = "Publisher identities require review"
            return [], 0, 0

        def _tag_owned(self, paper_ids):
            pass

    monkeypatch.setattr(run_crawl, "CrawlPipeline", Pipeline)
    monkeypatch.setattr(run_crawl, "db_file_path", lambda: Path(engine.url.database))
    monkeypatch.setattr(sys, "argv", ["run_crawl", "--years", *map(str, outcomes)])


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected", [
    ("ok", "success"), ("partial", "partial"),
    ("conflict", "partial"), ("empty", "partial"), ("failed", "failed"),
])
async def test_manual_run_records_honest_unit_and_aggregate_status(
    monkeypatch, engine, db, sample_venue, capsys, outcome, expected,
):
    configure_crawl(monkeypatch, engine, {2026: outcome})
    await run_crawl.main()
    db.expire_all()
    aggregate = db.query(CrawlLog).filter(CrawlLog.year.is_(None)).one()
    unit = db.query(CrawlLog).filter(CrawlLog.year == 2026).one()
    assert aggregate.status == unit.status == expected
    assert aggregate.finished_at and unit.finished_at
    checkpoints = db.query(CrawlState).all()
    assert len(checkpoints) == int(expected == "success")
    if checkpoints:
        assert checkpoints[0].cursor == "complete-v6"
    output = capsys.readouterr().out
    summary = json.loads(output.split("SUMMARY ", 1)[1])
    assert summary["ok"] == int(expected == "success")
    assert summary["partial"] == int(expected == "partial")
    assert summary["failed"] == int(expected == "failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["partial", "conflict", "failed"])
async def test_partial_or_failed_unit_does_not_taint_next_unit(
    monkeypatch, engine, db, sample_venue, first,
):
    configure_crawl(monkeypatch, engine, {2025: first, 2026: "ok"})
    await run_crawl.main()
    db.expire_all()
    assert db.query(CrawlLog).filter(CrawlLog.year.is_(None)).one().status == "partial"
    assert db.query(CrawlLog).filter(CrawlLog.year == 2026).one().status == "success"
    state = db.query(CrawlState).one()
    assert state.scope_key.endswith(":2026")
    assert state.cursor == "complete-v6"
