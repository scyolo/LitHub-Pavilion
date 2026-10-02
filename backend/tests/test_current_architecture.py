"""Keep the shipped source aligned with the link-only snapshot architecture."""
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.bootstrap import initialize_database, seed_missing
from app.config import PROJECT_ROOT, Settings
from app.models import Direction, Paper, Venue
from app.services.pipeline import CrawlPipeline


RETIRED_PATHS = (
    "backend/app/collectors/pdf_downloader.py",
    "backend/scripts/extend_topics.py",
    "seeds/pdf_whitelist.csv",
    "系统设计方案.md",
    "设计审查报告.md",
    "界面改版与验收.md",
    "发布验收.md",
)


def test_only_current_architecture_sources_are_shipped():
    assert (PROJECT_ROOT / "ARCHITECTURE.md").is_file()
    assert not [path for path in RETIRED_PATHS if (PROJECT_ROOT / path).exists()]


def test_retired_pdf_environment_cannot_enable_downloads(monkeypatch):
    monkeypatch.setenv("PDF_DOWNLOAD_ENABLED", "true")
    monkeypatch.setenv("PAPERS_ROOT", "/unused-archive")
    monkeypatch.setenv("PDF_DAILY_LIMIT", "5000")
    monkeypatch.setenv("ARXIV_INTERVAL_S", "3")
    config = Settings(_env_file=None)
    for name in ("pdf_download_enabled", "papers_root", "pdf_daily_limit", "arxiv_interval_s"):
        assert not hasattr(config, name)
    assert not hasattr(CrawlPipeline, "submit_pdf_backlog")


def test_bootstrap_needs_only_current_seed_files_and_preserves_legacy_tables(engine, tmp_path, seed_venue_abbrs):
    directory = tmp_path / "seeds"
    directory.mkdir()
    for name in ("venues.csv", "directions.csv", "direction_rules.csv"):
        (directory / name).write_bytes((PROJECT_ROOT / "seeds" / name).read_bytes())
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE pdf_whitelist (host TEXT PRIMARY KEY, note TEXT)")
        connection.exec_driver_sql("INSERT INTO pdf_whitelist VALUES ('archive.example.org', 'keep local history')")
    initialize_database(engine, directory)
    with Session(engine) as session:
        assert {abbr for abbr, in session.query(Venue.abbr)} == seed_venue_abbrs
        assert session.query(Direction).count() == 16
        seed_missing(session, directory)
        assert {abbr for abbr, in session.query(Venue.abbr)} == seed_venue_abbrs
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT host, note FROM pdf_whitelist").all() == [
            ("archive.example.org", "keep local history")
        ]


def test_fresh_database_has_no_download_whitelist(engine):
    initialize_database(engine, PROJECT_ROOT / "seeds")
    assert "pdf_whitelist" not in inspect(engine).get_table_names()


def test_new_model_rows_are_not_queued_for_download(db, sample_venue):
    paper = Paper(source="manual", title="Link-only metadata", title_norm="link only metadata",
                  venue_id=sample_venue.id, year=2026, ccf_level="A", doi="10.5555/link-only",
                  official_url="https://doi.org/10.5555/link-only")
    db.add(paper)
    db.commit()
    assert paper.pdf_status == "closed"


def test_scheduler_registers_only_current_jobs_without_download_settings(monkeypatch):
    import app.services.scheduler as module

    class Scheduler:
        def __init__(self, **kwargs):
            self.jobs = {}
            self.started = False

        def add_job(self, function, trigger, **kwargs):
            self.jobs[kwargs["id"]] = (function, trigger, kwargs)

        def start(self):
            self.started = True

    async def submit():
        return True

    monkeypatch.setattr(module, "AsyncIOScheduler", Scheduler)
    monkeypatch.setattr(module, "settings", SimpleNamespace(timezone="Asia/Shanghai"))
    pipeline = SimpleNamespace(submit_weekly=submit, submit_links_backfill=submit, submit_monthly_metrics=submit)
    scheduler = module.start_scheduler(pipeline)
    assert scheduler.started
    assert set(scheduler.jobs) == {"weekly_crawl", "links_backfill", "monthly_metrics"}
    _, trigger, options = scheduler.jobs["links_backfill"]
    assert str(trigger.timezone) == "Asia/Shanghai"
    fields = {field.name: str(field) for field in trigger.fields}
    assert (fields["day_of_week"], fields["hour"], fields["minute"]) == ("tue", "6", "30")
    assert options["args"] == [pipeline.submit_links_backfill]


@pytest.mark.parametrize("path", ["backend/app/**", "backend/requirements*.txt"])
def test_pages_rebuilds_when_validation_dependencies_change(path):
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert f"- '{path}'" in workflow


def test_frontend_ci_installs_python_exporter_dependencies_before_fixture_tests():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    frontend = workflow.split("  frontend:\n", 1)[1].split("\n  containers:", 1)[0]
    setup = "actions/setup-python@v5"
    dependencies = "python -m pip install -r ../backend/requirements.txt"
    tests = "npm test"
    assert setup in frontend, "Frontend wire-format tests execute the Python snapshot exporter"
    assert dependencies in frontend, "The fixture exporter needs its actual runtime dependencies"
    assert frontend.index(setup) < frontend.index(dependencies) < frontend.index(tests)
