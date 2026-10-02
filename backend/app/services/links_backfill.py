"""Weekly link-only maintenance. Existing archives are never deleted or overwritten."""
import logging

from sqlalchemy import func, or_

from app.api.serializers import arxiv_url, safe_http_url
from app.collectors.http_client import make_client
from app.config import settings
from app.cleaning import normalize_doi
from app.models import CrawlState, Paper
from app.ratelimit import AsyncTokenBucket

log = logging.getLogger("lithub.links_backfill")
CURSOR_KEY = "links_backfill:last_id"


def _best_oa(work: dict) -> str | None:
    best = work.get('best_oa_location')
    best = best if isinstance(best, dict) else {}
    access = work.get('open_access')
    access = access if isinstance(access, dict) else {}
    candidates = [best.get('pdf_url'), best.get('landing_page_url'), access.get('oa_url')]
    # Other locations are eligible only when the provider explicitly marks OA.
    locations = work.get('locations') or []
    if isinstance(locations, list):
        for location in locations:
            if isinstance(location, dict) and location.get('is_oa') is True:
                candidates.extend([location.get('pdf_url'), location.get('landing_page_url')])
    for value in candidates:
        if isinstance(value, str) and (link := safe_http_url(value)):
            return link
    return None


async def run_links_backfill(session_factory) -> dict:
    stats = {"flipped": 0, "arxiv_filled": 0, "openalex_filled": 0, "paused": False}
    with session_factory() as session:
        # Historical archive metadata remains intact; this job only maintains external links.
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
                targets = session.query(Paper.id, Paper.openalex_id, Paper.doi).filter(
                    Paper.id > after, or_(Paper.openalex_id.isnot(None), Paper.doi.isnot(None)),
                    or_(Paper.oa_url.is_(None), func.trim(Paper.oa_url) == ""),
                ).order_by(Paper.id).limit(50).all()
                if not targets:
                    if checkpoint:
                        checkpoint.cursor = "0"
                        session.commit()
                    break
            links, doi_links = {}, {}
            groups = [("openalex", [oid.rsplit("/", 1)[-1] for _, oid, _ in targets if oid]),
                      ("doi", [normalize_doi(doi) for _, oid, doi in targets if not oid and normalize_doi(doi)])]
            for field, identifiers in groups:
                if not identifiers:
                    continue
                await limiter.acquire()
                response = await client.get("https://api.openalex.org/works", params={
                    "filter": field + ":" + "|".join(identifiers),
                    "per-page": 50, "select": "id,doi,best_oa_location,open_access", "mailto": settings.contact_email,
                })
                if response.status_code in (401, 403, 429):
                    stats["paused"] = True
                    log.warning("Link backfill paused: HTTP %d; resume next weekly run", response.status_code)
                    break
                response.raise_for_status()
                values = response.json().get("results")
                if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                    raise ValueError("Invalid OpenAlex response")
                for item in values:
                    link = safe_http_url(_best_oa(item))
                    links[str(item.get("id", "")).rsplit("/", 1)[-1]] = link
                    if doi := normalize_doi(item.get("doi")):
                        doi_links[doi] = link
            if stats["paused"]:
                break
            with session_factory() as session:
                for paper_id, oid, doi in targets:
                    paper = session.get(Paper, paper_id)
                    link = links.get(oid.rsplit("/", 1)[-1]) if oid else doi_links.get(normalize_doi(doi))
                    if paper is not None and not safe_http_url(paper.oa_url) and link:
                        paper.oa_url = link
                        stats["openalex_filled"] += 1
                checkpoint = session.query(CrawlState).filter(CrawlState.scope_key == CURSOR_KEY).one_or_none()
                if checkpoint is None:
                    session.add(CrawlState(scope_key=CURSOR_KEY, cursor=str(targets[-1][0])))
                else:
                    checkpoint.cursor = str(targets[-1][0])
                session.commit()
    with session_factory() as session:
        stats["remaining"] = session.query(Paper).filter(or_(Paper.oa_url.is_(None), func.trim(Paper.oa_url) == ""), or_(Paper.openalex_id.isnot(None), Paper.doi.isnot(None))).count()
    log.info("Link backfill result: %s", stats)
    return stats
