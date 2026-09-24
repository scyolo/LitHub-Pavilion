"""Startup collection and publication stay asynchronous, bounded, and recoverable."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.pipeline import CrawlPipeline


@pytest.mark.asyncio
async def test_startup_collects_history_then_recent_years_once(session_factory, monkeypatch):
    complete = AsyncMock()
    pipeline = CrawlPipeline(session_factory, on_complete=complete)
    current = datetime.now(timezone.utc).year
    run = AsyncMock()
    monkeypatch.setattr(pipeline, "_run", run)
    assert await pipeline.submit_startup(list(range(current - 3, current + 1)))
    assert not await pipeline.submit_startup([current])
    await pipeline.wait_idle()
    assert [call.args[0] for call in run.await_args_list] == ["backfill", "weekly"]
    assert run.await_args_list[0].kwargs["years"] == [current - 3, current - 2]
    assert run.await_args_list[1].kwargs["years"] == [current - 1, current]
    complete.assert_awaited_once()
    assert not pipeline.status.running


@pytest.mark.asyncio
async def test_cancelled_collection_never_publishes(session_factory, monkeypatch):
    complete = AsyncMock()
    pipeline = CrawlPipeline(session_factory, on_complete=complete)
    started = asyncio.Event()

    async def run(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(pipeline, "_run", run)
    await pipeline.submit_weekly()
    await started.wait()
    await pipeline.shutdown()
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_publication_callback_error_does_not_mark_collection_failed(session_factory, monkeypatch):
    complete = AsyncMock(side_effect=RuntimeError("publisher failed"))
    pipeline = CrawlPipeline(session_factory, on_complete=complete)
    monkeypatch.setattr(pipeline, "_run", AsyncMock())
    await pipeline.submit_weekly()
    await pipeline.wait_idle()
    assert not pipeline.status.running
    assert pipeline.status.last_error is None


def test_startup_year_configuration_is_bounded():
    for arguments in ({"startup_year_from": 1999}, {"startup_year_from": 2026, "startup_year_to": 2025}, {"startup_year_from": 2000, "startup_year_to": 2050}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **arguments)
    settings = Settings(_env_file=None, startup_year_from=2023, startup_year_to=2026)
    assert settings.startup_years == [2023, 2024, 2025, 2026]


@pytest.mark.asyncio
async def test_startup_exports_existing_data_and_submits_configured_years(session_factory, sample_paper, tmp_path):
    from app.services.site_sync import SiteSync

    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", startup_crawl_enabled=True,
                      startup_year_from=2023, startup_year_to=2026, pages_publish_enabled=False)
    pipeline = CrawlPipeline(session_factory)
    pipeline.submit_startup = AsyncMock(return_value=True)
    sync = SiteSync(session_factory, pipeline, config=config)
    sync.start()
    await sync.wait_startup()
    pipeline.submit_startup.assert_awaited_once_with([2023, 2024, 2025, 2026])
    assert (config.snapshot_dir / "manifest.json").exists()
    assert sync.status()["snapshot_status"] == "ready"
    assert sync.status()["publication_status"] == "disabled"
    await sync.shutdown()


@pytest.mark.asyncio
async def test_failed_collection_leaves_existing_snapshot_readable(session_factory, sample_paper, tmp_path):
    from app.services.site_sync import SiteSync
    from app.services.snapshot import validate_snapshot

    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot")
    sync = SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await sync.refresh()
    first = validate_snapshot(config.snapshot_dir)
    await sync.refresh()
    assert validate_snapshot(config.snapshot_dir) == first
    assert sync.status()["paper_count"] == 1


@pytest.mark.asyncio
async def test_empty_startup_does_not_publish_or_prevent_collection(session_factory, tmp_path, monkeypatch):
    import app.services.site_sync as module

    publisher = AsyncMock()
    monkeypatch.setattr(module, "publish_snapshot", publisher)
    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", startup_crawl_enabled=True,
                      pages_publish_enabled=True, pages_repository="owner/repo")
    pipeline = CrawlPipeline(session_factory)
    pipeline.submit_startup = AsyncMock(return_value=True)
    sync = module.SiteSync(session_factory, pipeline, config=config)
    sync.start()
    await sync.wait_startup()
    publisher.assert_not_awaited()
    pipeline.submit_startup.assert_awaited_once()
    assert sync.status()["snapshot_status"] == "waiting_for_data"
    await sync.shutdown()


@pytest.mark.asyncio
async def test_publication_failure_is_safe_and_retryable(session_factory, sample_paper, tmp_path, monkeypatch):
    import app.services.site_sync as module
    from app.services.snapshot import validate_snapshot

    secret = tmp_path / "token"
    secret.write_text("not-for-public-output", encoding="utf-8")
    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", pages_publish_enabled=True,
                      pages_repository="owner/repo", pages_token_file=secret)
    publisher = AsyncMock(side_effect=RuntimeError("not-for-public-output"))
    monkeypatch.setattr(module, "publish_snapshot", publisher)
    sync = module.SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await sync.refresh()
    manifest = validate_snapshot(config.snapshot_dir)
    assert sync.status()["snapshot_status"] == "ready"
    assert sync.status()["publication_status"] == "failed"
    assert "not-for-public-output" not in str(sync.status())
    publisher.side_effect = None
    publisher.return_value = {"state": "dispatched", "commit": "a" * 40, "revision": manifest["revision"]}
    await sync.retry_publication()
    assert sync.status()["publication_status"] == "dispatched"
    assert sync.status()["commit"] == "a" * 40
    assert publisher.await_count == 2
    await sync.refresh()
    assert publisher.await_count == 2
    restarted = module.SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await restarted.refresh()
    assert publisher.await_count == 2


@pytest.mark.asyncio
async def test_missing_credentials_keep_local_snapshot_usable(session_factory, sample_paper, tmp_path):
    from app.services.site_sync import SiteSync

    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", pages_publish_enabled=True,
                      pages_repository="owner/repo", pages_token_file=tmp_path / "missing-token")
    sync = SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await sync.refresh()
    assert sync.status()["snapshot_status"] == "ready"
    assert sync.status()["publication_status"] == "needs_credentials"


def test_lifespan_starts_and_stops_site_sync(client):
    assert hasattr(client.app.state, "site_sync")
    status = client.get("/api/crawl/status").json()
    assert "site_sync" in status
    assert status["site_sync"]["snapshot_status"] == "disabled"
    assert status["site_sync"]["publication_status"] == "disabled"
    assert not status["site_sync"]["startup_crawl_enabled"]


def test_empty_end_year_and_configured_weekly_range(monkeypatch):
    monkeypatch.setenv("STARTUP_YEAR_TO", "")
    config = Settings(_env_file=None, startup_year_from=2023)
    assert config.startup_year_to is None
    assert config.weekly_years == config.startup_years[-2:]
    assert Settings(_env_file=None, startup_year_from=2023, startup_year_to=2024).weekly_years == [2023, 2024]
    assert Settings(_env_file=None, startup_year_from=2024, startup_year_to=2024).weekly_years == [2024]


@pytest.mark.asyncio
async def test_startup_collection_does_not_wait_for_a_slow_publisher(session_factory, tmp_path, monkeypatch):
    from app.services.site_sync import SiteSync

    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", startup_crawl_enabled=True)
    pipeline = CrawlPipeline(session_factory)
    pipeline.submit_startup = AsyncMock(return_value=True)
    sync = SiteSync(session_factory, pipeline, config=config)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_refresh():
        entered.set()
        await release.wait()

    monkeypatch.setattr(sync, "refresh", slow_refresh)
    sync.start()
    await entered.wait()
    pipeline.submit_startup.assert_awaited_once_with(config.startup_years)
    release.set()
    await sync.wait_startup()
    await sync.shutdown()


@pytest.mark.asyncio
async def test_busy_startup_waits_and_retries_without_losing_requested_collection(session_factory, tmp_path, monkeypatch):
    from app.services.site_sync import SiteSync

    config = Settings(_env_file=None, snapshot_enabled=False, startup_crawl_enabled=True)
    pipeline = CrawlPipeline(session_factory)
    pipeline.submit_startup = AsyncMock(side_effect=[False, True])
    pipeline.wait_idle = AsyncMock()
    sync = SiteSync(session_factory, pipeline, config=config)
    sync.start()
    await sync.wait_startup()
    assert pipeline.submit_startup.await_count == 2
    pipeline.wait_idle.assert_awaited_once()
    await sync.shutdown()


@pytest.mark.asyncio
async def test_deployment_is_confirmed_by_online_revision_and_failed_build_is_retried(session_factory, sample_paper, tmp_path, monkeypatch):
    import app.services.site_sync as module
    from app.services.snapshot import export_snapshot

    secret = tmp_path / "token"
    secret.write_text("local-test-token", encoding="utf-8")
    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", pages_publish_enabled=True,
                      pages_repository="owner/repo", pages_token_file=secret, pages_deploy_retry_seconds=300)
    manifest = export_snapshot(session_factory, config.snapshot_dir)
    publisher = AsyncMock(return_value={"state": "dispatched", "commit": "a" * 40, "revision": manifest["revision"]})
    online = AsyncMock(return_value=None)
    monkeypatch.setattr(module, "publish_snapshot", publisher)
    monkeypatch.setattr(module, "deployed_revision", online)
    sync = module.SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await sync.refresh()
    await sync.retry_publication()
    assert publisher.await_count == 1
    assert sync.status()["publication_status"] == "dispatched"
    sync._dispatched_at -= 301
    await sync.retry_publication()
    assert publisher.await_count == 2
    online.return_value = manifest["revision"]
    await sync.retry_publication()
    assert sync.status()["publication_status"] == "deployed"
    assert publisher.await_count == 2
    restarted = module.SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await restarted.refresh()
    assert restarted.status()["publication_status"] == "deployed"
    assert publisher.await_count == 2


@pytest.mark.asyncio
async def test_deployment_check_failure_does_not_claim_success_or_repeat_upload(session_factory, sample_paper, tmp_path, monkeypatch):
    import app.services.site_sync as module
    from app.services.snapshot import export_snapshot

    secret = tmp_path / "token"
    secret.write_text("token", encoding="utf-8")
    config = Settings(_env_file=None, snapshot_enabled=True, snapshot_dir=tmp_path / "snapshot", pages_publish_enabled=True,
                      pages_repository="owner/repo", pages_token_file=secret)
    manifest = export_snapshot(session_factory, config.snapshot_dir)
    publisher = AsyncMock(return_value={"state": "dispatched", "commit": "a" * 40, "revision": manifest["revision"]})
    monkeypatch.setattr(module, "publish_snapshot", publisher)
    monkeypatch.setattr(module, "deployed_revision", AsyncMock(side_effect=RuntimeError("network details")))
    sync = module.SiteSync(session_factory, CrawlPipeline(session_factory), config=config)
    await sync.refresh()
    await sync.retry_publication()
    assert sync.status()["publication_status"] == "dispatched"
    assert "network details" not in str(sync.status())
    publisher.assert_awaited_once()
