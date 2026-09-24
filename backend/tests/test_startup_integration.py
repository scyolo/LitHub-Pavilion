"""Exercise real lifespan orchestration against an isolated database and mocked paper sources."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.services.pipeline import CrawlPipeline
from app.services.snapshot import validate_snapshot


def test_lifespan_collects_and_exports_without_blocking_health(engine, session_factory, sample_paper, tmp_path, monkeypatch):
    import app.api.main as main
    import app.db as database

    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_SessionLocal", session_factory)
    for name, value in {"initialize_on_startup": False, "scheduler_enabled": False, "startup_crawl_enabled": True,
                        "startup_year_from": 2024, "startup_year_to": 2024, "snapshot_enabled": True,
                        "snapshot_dir": tmp_path / "public", "pages_publish_enabled": False}.items():
        monkeypatch.setattr(main.settings, name, value)
    collect = AsyncMock(return_value=([], False))
    monkeypatch.setattr(CrawlPipeline, "_probe", AsyncMock(return_value=SimpleNamespace(ok=True, reason="isolated fixture")))
    monkeypatch.setattr(CrawlPipeline, "_collect_unit_async", collect)
    monkeypatch.setattr(CrawlPipeline, "_maybe_alert", AsyncMock())
    with TestClient(main.create_app()) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = client.get("/api/crawl/status").json()
            if collect.await_count and not state["running"] and state["site_sync"]["snapshot_status"] == "ready":
                break
            time.sleep(0.02)
        else:
            pytest.fail("Startup collection did not finish and export in time")
        assert [call.args[2] for call in collect.await_args_list] == [2024]
        assert state["site_sync"]["paper_count"] == 1
        assert state["site_sync"]["publication_status"] == "disabled"
        assert validate_snapshot(tmp_path / "public")["paper_count"] == 1
        assert client.get("/api/papers").json()["total"] == 1


@pytest.mark.asyncio
async def test_weekly_collection_uses_configured_range_not_machine_year(session_factory, sample_venue, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "startup_year_from", 2023)
    monkeypatch.setattr(settings, "startup_year_to", 2024)
    pipeline = CrawlPipeline(session_factory)
    monkeypatch.setattr(pipeline, "_probe", AsyncMock(return_value=SimpleNamespace(ok=True, reason="fixture")))
    collect = AsyncMock(return_value=([], False))
    monkeypatch.setattr(pipeline, "_collect_unit_async", collect)
    monkeypatch.setattr(pipeline, "_maybe_alert", AsyncMock())
    assert await pipeline.submit_weekly()
    await pipeline.wait_idle()
    assert [call.args[2] for call in collect.await_args_list] == [2023, 2024]


@pytest.mark.asyncio
async def test_scheduled_work_waits_instead_of_dropping_a_busy_submission(session_factory, monkeypatch):
    from app.services.scheduler import start_scheduler

    pipeline = CrawlPipeline(session_factory)
    submit = AsyncMock(side_effect=[False, True])
    submit.__name__ = "submit_weekly"
    monkeypatch.setattr(pipeline, "submit_weekly", submit)
    monkeypatch.setattr(pipeline, "wait_idle", AsyncMock())
    scheduler = start_scheduler(pipeline)
    try:
        job = scheduler.get_job("weekly_crawl")
        await job.func(*job.args)
        assert submit.await_count == 2
        pipeline.wait_idle.assert_awaited_once()
    finally:
        scheduler.shutdown(wait=False)
