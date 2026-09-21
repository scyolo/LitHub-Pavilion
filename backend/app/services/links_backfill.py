"""Weekly link-only maintenance. Existing archives are never deleted or overwritten."""
import logging

from sqlalchemy import func, or_

from app.api.serializers import arxiv_url, safe_http_url
from app.collectors.http_client import make_client
from app.config import settings
from app.models import CrawlState, Paper
from app.ratelimit import AsyncTokenBucket

log = logging.getLogger("lithub.links_backfill")
CURSOR_KEY = "links_backfill:last_id"


def _best_oa(work: dict) -> str | None:
    location = work.get("best_oa_location") or {}
    pdf = location.get("pdf_url") if isinstance(location, dict) else None
    return pdf or (work.get("open_access") or {}).get("oa_url") or None


async def run_links_backfill(session_factory) -> dict:
    if settings.pdf_download_enabled:
        raise ValueError("Link backfill requires link-only mode")
    stats = {"flipped": 0, "pdf_removed": 0, "arxiv_filled": 0, "openalex_filled": 0, "paused": False}
    with session_factory() as session:
        # Legacy downloaded rows and their paths stay intact; switching mode is not deletion consent.
        rows = session.query(Paper).filter(Paper.pdf_status.in_(("pending", "failed"))).all()
        for paper in rows:
            paper.pdf_status = "closed"
        stats["flipped"] = len(rows)
        for paper in session.query(Paper).filter(Paper.arxiv_id.isnot(None), or_(Paper.oa_url.is_(None), func.trim(Paper.oa_url) == "")).all():
            link = arxiv_url(paper.arxiv_id)
            if link:
                paper.oa_url = link
                stats["arxiv_filled"] += 1
        session.commit()

    limiter = AsyncTokenBucket(settings.openalex_rps)
    async with make_client() as client:
        for _ in range(settings.links_max_batches):
            with session_factory() as session:
                checkpoint = session.query(CrawlState).filter(CrawlState.scope_key == CURSOR_KEY).one_or_none()
                try:
                    after = int(checkpoint.cursor) if checkpoint else 0
                except ValueError:
                    after = 0
                targets = session.query(Paper.id, Paper.openalex_id).filter(
                    Paper.id > after, Paper.openalex_id.isnot(None),
                    or_(Paper.oa_url.is_(None), func.trim(Paper.oa_url) == ""),
                ).order_by(Paper.id).limit(50).all()
                if not targets:
                    if checkpoint:
                        checkpoint.cursor = "0"
                        session.commit()
                    break
            await limiter.acquire()
            response = await client.get("https://api.openalex.org/works", params={
                "filter": "openalex:" + "|".join(oid for _, oid in targets),
                "per-page": 50, "select": "id,best_oa_location,open_access", "mailto": settings.contact_email,
            })
            if response.status_code in (401, 403, 429):
                stats["paused"] = True
                log.warning("Link backfill paused: HTTP %d; resume next weekly run", response.status_code)
                break
            response.raise_for_status()
            values = response.json().get("results")
            if not isinstance(values, list):
                raise ValueError("Invalid OpenAlex response")
            links = {str(item.get("id", "")).rsplit("/", 1)[-1]: safe_http_url(_best_oa(item)) for item in values}
            with session_factory() as session:
                for paper_id, oid in targets:
                    paper = session.get(Paper, paper_id)
                    if paper is not None and not safe_http_url(paper.oa_url) and links.get(oid):
                        paper.oa_url = links[oid]
                        stats["openalex_filled"] += 1
                checkpoint = session.query(CrawlState).filter(CrawlState.scope_key == CURSOR_KEY).one_or_none()
                if checkpoint is None:
                    session.add(CrawlState(scope_key=CURSOR_KEY, cursor=str(targets[-1][0])))
                else:
                    checkpoint.cursor = str(targets[-1][0])
                session.commit()
    with session_factory() as session:
        stats["remaining"] = session.query(Paper).filter(Paper.oa_url.is_(None), Paper.openalex_id.isnot(None)).count()
    log.info("Link backfill result: %s", stats)
    return stats
