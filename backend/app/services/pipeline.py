"""Single active job, honest checkpoints, and task-owned database sessions."""
import asyncio
import logging
import smtplib
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from app.cleaning import is_noise_title, normalize_title
from app.collectors.dblp import fetch_toc, probe_dblp, toc_key_for
from app.collectors.http_client import make_client
from app.collectors.openalex import OpenAlexBudgetExhausted, fetch_works_by_source, resolve_source_id, work_to_raw_paper
from app.collectors.s2 import fetch_bulk_raw_papers
from app.config import settings
from app.models import CrawlLog, CrawlState, Paper, Venue, utcnow_iso
from app.ratelimit import AsyncTokenBucket
from app.services.enrichment import enrich_papers
from app.services.paper_store import upsert_paper as upsert_paper
from app.services.tagging import apply_tagging, load_rules, load_thresholds

log = logging.getLogger("lithub.pipeline")
BATCH_SIZE = 100


class CrawlRun:
    def __init__(self):
        self.running = False
        self.run_id = None
        self.current = None
        self.progress = None
        self.last_error = None


class CrawlPipeline:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.status = CrawlRun()
        self._task = None
        self._closing = False
        self._stopping = False
        self._openalex_paused_until = 0.0
        self._limiters = {}
        self._collection_issue = None
        self._active_session = None

    def _start(self, factory: Callable, *, run_id: str | None = None) -> bool:
        if self.status.running or self._closing:
            return False
        run_id = run_id or "c-" + uuid.uuid4().hex[:12]
        self.status.running = True
        self.status.run_id = run_id
        self.status.current = None
        self.status.progress = None
        self.status.last_error = None
        self._task = asyncio.create_task(self._guard(factory), name=run_id)
        return True

    async def _guard(self, factory):
        try:
            await factory()
        except asyncio.CancelledError:
            self.status.last_error = "Task cancelled during shutdown"
            if self._active_session is not None:
                self._active_session.rollback()
            self._mark_interrupted()
            raise
        except Exception as exc:
            self.status.last_error = type(exc).__name__
            log.exception("Background task failed")
            self._mark_interrupted()
        finally:
            self.status.running = False
            self.status.current = None
            self.status.progress = None
            self._active_session = None

    def _mark_interrupted(self):
        try:
            with self.session_factory() as session:
                logs = session.query(CrawlLog).filter(CrawlLog.run_id == self.status.run_id, CrawlLog.status == "running").all()
                for row in logs:
                    row.status = "failed"
                    row.error = "Interrupted before completion"
                    row.finished_at = utcnow_iso()
                session.commit()
        except Exception:
            log.exception("Could not record interrupted task")

    async def wait_idle(self):
        if self._task:
            await asyncio.shield(self._task)

    async def shutdown(self):
        self._closing = True
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self.status.running = False
        self.status.current = None
        self.status.progress = None

    async def _db_call(self, function, *args):
        # Cancellation must not close a Session while its worker still owns it.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def submit_weekly(self, run_id=None):
        run_id = run_id or "c-" + uuid.uuid4().hex[:12]
        return self._start(lambda: self._run("weekly", run_id=run_id), run_id=run_id)

    async def submit_backfill(self, years=None, run_id=None):
        run_id = run_id or "c-" + uuid.uuid4().hex[:12]
        return self._start(lambda: self._run("backfill", years=years or [2023, 2024, 2025], run_id=run_id), run_id=run_id)

    async def submit_reclassify(self, run_id=None):
        run_id = run_id or "r-" + uuid.uuid4().hex[:12]
        return self._start(lambda: self._maintenance("reclassify", run_id), run_id=run_id)

    async def submit_monthly_metrics(self):
        run_id = "m-" + uuid.uuid4().hex[:12]
        return self._start(lambda: self._maintenance("monthly", run_id), run_id=run_id)

    async def submit_pdf_backlog(self):
        # The published product is link-only. Retained API rejects download requests explicitly.
        return False

    async def submit_links_backfill(self):
        from app.services.links_backfill import run_links_backfill
        run_id = "l-" + uuid.uuid4().hex[:12]
        return self._start(lambda: run_links_backfill(self.session_factory), run_id=run_id)

    async def _probe(self):
        async with make_client() as client:
            return await probe_dblp(client, settings.dblp_base_url)

    def _limiter(self, name, rate):
        if name not in self._limiters:
            self._limiters[name] = AsyncTokenBucket(rate)
        return self._limiters[name]

    async def _collect_unit_async(self, session: Session, venue: Venue, year: int, use_dblp: bool):
        self._collection_issue = None
        papers = []
        failures = []
        if use_dblp and venue.type == "conf" and venue.dblp_toc_pattern:
            try:
                async with make_client() as client:
                    papers = await fetch_toc(client, self._limiter("dblp", settings.dblp_rps), settings.dblp_base_url, toc_key_for(venue.dblp_stream, venue.dblp_toc_pattern, year))
                if papers:
                    return papers, False
            except (httpx.HTTPError, ValueError) as exc:
                failures.append("DBLP:" + type(exc).__name__)
        source = venue.openalex_source_id or venue.issn
        if time.monotonic() >= self._openalex_paused_until:
            try:
                async with make_client() as client:
                    limiter = self._limiter("openalex", settings.openalex_rps)
                    if not source:
                        source = await resolve_source_id(client, limiter, venue.name, settings.contact_email)
                        if source:
                            venue.openalex_source_id = source
                            session.commit()
                    if source:
                        works = await fetch_works_by_source(client, limiter, settings.contact_email, source, [year])
                        for work in works:
                            _, raw = work_to_raw_paper(work, "https://dblp.org/db/" + venue.dblp_stream + "/")
                            if raw:
                                papers.append(raw)
            except OpenAlexBudgetExhausted:
                self._openalex_paused_until = time.monotonic() + 3600
                failures.append("OpenAlex:budget or rate limited")
            except (httpx.HTTPError, ValueError) as exc:
                failures.append("OpenAlex:" + type(exc).__name__)
        else:
            failures.append("OpenAlex:paused")
        used_fallback = False
        if venue.type == "conf" and venue.s2_venue and len(papers) < settings.openalex_low_yield:
            used_fallback = True
            try:
                papers.extend(await fetch_bulk_raw_papers(venue, year, settings.s2_bulk_queries, settings.s2_api_key, settings.s2_rps))
            except Exception as exc:
                failures.append("Semantic Scholar:" + type(exc).__name__)
        # Empty, filtered fallback, and interrupted source collection are not full coverage checkpoints.
        if not papers or failures or used_fallback:
            self._collection_issue = "; ".join(failures) or ("Topic-filtered fallback; full coverage unverified" if used_fallback else "No records; coverage unverified")
        return papers, not papers or bool(failures) or used_fallback

    def _ingest_batch_sync(self, session, raw_batch, venue, unit_year):
        papers, created, updated, cache = [], 0, 0, {}
        for raw in raw_batch:
            if not 2000 <= raw.year <= 2100 or (raw.source == "dblp" and raw.year != unit_year):
                continue
            if is_noise_title(normalize_title(raw.title)):
                continue
            paper, new = upsert_paper(session, raw, venue, author_cache=cache)
            created += int(new)
            updated += int(not new)
            papers.append(paper)
        session.commit()
        return papers, created, updated

    def _ingest_owned(self, raw_batch, venue_id, year):
        with self.session_factory() as session:
            venue = session.get(Venue, venue_id)
            papers, created, updated = self._ingest_batch_sync(session, raw_batch, venue, year)
            return [paper.id for paper in papers], created, updated

    def _tag_owned(self, paper_ids):
        with self.session_factory() as session:
            rules, thresholds = load_rules(session), load_thresholds(session)
            for paper in session.query(Paper).filter(Paper.id.in_(paper_ids)).all():
                apply_tagging(session, paper.id, paper.title, paper.abstract, rules, thresholds)
            session.commit()

    async def _run(self, task_type, years=None, run_id=None):
        session = self.session_factory()
        self._active_session = session
        run = CrawlLog(run_id=run_id, task_type=task_type, status="running", started_at=utcnow_iso())
        new_count = updated_count = successes = partials = failures = 0
        try:
            session.add(run)
            session.commit()
            probe = await self._probe()
            run.error = probe.reason
            session.commit()
            years = sorted(set(years or [datetime.now(timezone.utc).year - 1, datetime.now(timezone.utc).year]))
            venues = session.query(Venue).filter(Venue.active == 1, Venue.ccf_level.in_(("A", "B"))).all()
            completed = 0
            total = len(venues) * len(years)
            for venue in venues:
                for year in years:
                    key = f"{task_type}:{venue.dblp_stream}:{year}"
                    checkpoint = session.query(CrawlState).filter(CrawlState.scope_key == key, CrawlState.cursor == "complete-v2").first()
                    if task_type == "backfill" and checkpoint:
                        completed += 1
                        self.status.progress = f"{completed}/{total}"
                        continue
                    unit = CrawlLog(run_id=run_id, task_type=task_type, venue_id=venue.id, status="running", started_at=utcnow_iso())
                    session.add(unit)
                    session.commit()
                    self.status.current = f"{venue.abbr}/{year}"
                    self.status.progress = f"{completed}/{total}"
                    try:
                        raws, incomplete = await self._collect_unit_async(session, venue, year, probe.ok)
                        for start in range(0, len(raws), BATCH_SIZE):
                            ids, new, updated = await self._db_call(self._ingest_owned, raws[start:start + BATCH_SIZE], venue.id, year)
                            unit.papers_new += new
                            unit.papers_updated += updated
                            new_count += new
                            updated_count += updated
                            session.commit()
                            async with make_client() as client:
                                with self.session_factory() as enrichment_session:
                                    papers = enrichment_session.query(Paper).filter(Paper.id.in_(ids)).all()
                                    enrichment = await enrich_papers(enrichment_session, papers, client)
                                    if enrichment and enrichment.get("failed"):
                                        incomplete = True
                            await self._db_call(self._tag_owned, ids)
                        unit.status = "partial" if incomplete or not raws else "success"
                        unit.error = self._collection_issue if incomplete else None
                        if unit.status == "success":
                            state = session.query(CrawlState).filter(CrawlState.scope_key == key).one_or_none()
                            if state is None:
                                session.add(CrawlState(scope_key=key, cursor="complete-v2"))
                            else:
                                state.cursor = "complete-v2"
                            successes += 1
                        else:
                            partials += 1
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        session.rollback()
                        unit.status = "failed"
                        unit.error = type(exc).__name__ + ": collection failed; see local logs"
                        failures += 1
                        log.exception("Collection unit failed: %s/%s", venue.abbr, year)
                    unit.finished_at = utcnow_iso()
                    session.add(unit)
                    session.commit()
                    completed += 1
                    self.status.progress = f"{completed}/{total}"
            run.status = "failed" if failures and not successes and not partials else "partial" if failures or partials else "success"
            run.error = f"complete={successes}; partial={partials}; failed={failures}; {probe.reason}"
        except asyncio.CancelledError:
            session.rollback()
            run.status = "failed"
            run.error = "Interrupted during shutdown; unfinished units will be retried"
            for row in session.query(CrawlLog).filter(CrawlLog.run_id == run_id, CrawlLog.status == "running").all():
                row.status = "failed"
                row.error = run.error
                row.finished_at = utcnow_iso()
            raise
        except Exception as exc:
            session.rollback()
            run.status = "failed"
            run.error = type(exc).__name__ + ": run failed"
            self.status.last_error = run.error
            log.exception("Collection run failed")
        finally:
            try:
                run.papers_new, run.papers_updated = new_count, updated_count
                run.finished_at = utcnow_iso()
                session.add(run)
                session.commit()
            finally:
                session.close()
                self._active_session = None
        await self._maybe_alert()

    async def _maintenance(self, task_type, run_id):
        with self.session_factory() as session:
            run = CrawlLog(run_id=run_id, task_type=task_type, status="running", started_at=utcnow_iso())
            session.add(run)
            session.commit()
            last_id, count, errors = 0, 0, 0
            try:
                while True:
                    ids = [value for (value,) in session.query(Paper.id).filter(Paper.id > last_id).order_by(Paper.id).limit(BATCH_SIZE).all()]
                    if not ids:
                        break
                    if task_type == "reclassify":
                        await self._db_call(self._tag_owned, ids)
                    else:
                        async with make_client() as client:
                            rows = session.query(Paper).filter(Paper.id.in_(ids)).all()
                            result = await enrich_papers(session, rows, client)
                            errors += (result or {}).get("failed", 0)
                    count += len(ids)
                    last_id = ids[-1]
                    self.status.progress = str(count)
                run.status = "partial" if errors else "success"
            except asyncio.CancelledError:
                session.rollback()
                run.status = "failed"
                run.error = "Interrupted during shutdown"
                raise
            except Exception:
                session.rollback()
                run.status = "failed"
                run.error = "Maintenance failed; see local logs"
                log.exception("Maintenance failed")
            finally:
                run.papers_updated = count
                run.finished_at = utcnow_iso()
                session.add(run)
                session.commit()

    async def _maybe_alert(self):
        if not all((settings.smtp_host, settings.alert_email, settings.smtp_user, settings.smtp_pass)):
            return
        with self.session_factory() as session:
            runs = session.query(CrawlLog).filter(CrawlLog.task_type == "weekly", CrawlLog.venue_id.is_(None)).order_by(CrawlLog.id.desc()).limit(3).all()
            should_alert = len(runs) == 3 and all(run.status == "failed" for run in runs)
        if should_alert:
            def send():
                message = EmailMessage()
                message["From"], message["To"] = settings.smtp_user, settings.alert_email
                message["Subject"] = "[LitHub Pavilion] 采集连续失败 3 次"
                message.set_content("请检查本地采集日志与来源可达性。")
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                    smtp.login(settings.smtp_user, settings.smtp_pass)
                    smtp.send_message(message)
            try:
                await asyncio.to_thread(send)
            except Exception:
                log.exception("Alert delivery failed")
