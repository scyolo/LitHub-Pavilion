"""Resumable link-only maintenance. Archives and valid existing URLs stay intact."""
import logging
import re

from sqlalchemy import func, or_, update

from app.api.serializers import arxiv_url, safe_http_url
from app.cleaning import normalize_doi
from app.collectors.http_client import make_client
from app.config import settings
from app.models import CrawlState, Paper
from app.ratelimit import AsyncTokenBucket
from app.services.open_access import best_openalex_url, publisher_open_url

log = logging.getLogger('lithub.links_backfill')
CURSOR_KEY = 'links_backfill:last_id'
_best_oa = best_openalex_url  # Compatibility for existing callers.


def backfill_local_links(session_factory, *, batch_size=2000) -> dict:
    """Repair the whole local corpus without network access, in bounded batches.

    Repeated runs are idempotent. Source counts describe new links, never the
    number of pages fetched or an assertion that all papers are freely readable.
    """
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    stats = {'flipped': 0, 'arxiv_filled': 0, 'publisher_filled': 0, 'by_source': {}}
    with session_factory() as session:
        stats['flipped'] = session.query(Paper).filter(Paper.pdf_status.in_(('pending', 'failed'))).update(
            {Paper.pdf_status: 'closed'}, synchronize_session=False)
        session.commit()
    after = 0
    while True:
        with session_factory() as session:
            # Keep the read/update pair atomic against a concurrent collector or manual edit.
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            rows = session.query(Paper.id, Paper.oa_url, Paper.arxiv_id, Paper.doi, Paper.publisher_key,
                                 Paper.official_url).filter(Paper.id > after).order_by(Paper.id).limit(batch_size).all()
            if not rows:
                break
            changes = []
            for row in rows:
                if safe_http_url(row.oa_url):
                    continue
                link = arxiv_url(row.arxiv_id)
                if link:
                    source = 'arXiv'
                    stats['arxiv_filled'] += 1
                else:
                    evidence = publisher_open_url(doi=row.doi, publisher_key=row.publisher_key, official_url=row.official_url)
                    if not evidence:
                        continue
                    link, source = evidence.url, evidence.source
                    stats['publisher_filled'] += 1
                changes.append({'id': row.id, 'oa_url': link})
                stats['by_source'][source] = stats['by_source'].get(source, 0) + 1
            if changes:
                session.execute(update(Paper), changes)
            session.commit()
            after = rows[-1].id
    return stats


def _openalex_key(value):
    key = value.rstrip('/').rsplit('/', 1)[-1] if isinstance(value, str) else ''
    return key if re.fullmatch(r'W\d+', key) else None


def _doi(value):
    return normalize_doi(value) if isinstance(value, str) else None


async def run_links_backfill(session_factory, *, local_only=False, max_batches=None) -> dict:
    batches = settings.links_max_batches if max_batches is None else max_batches
    if not isinstance(batches, int) or isinstance(batches, bool) or not 0 <= batches <= 200:
        raise ValueError('max_batches must be between 0 and 200')
    stats = {**backfill_local_links(session_factory), 'openalex_filled': 0, 'checked': 0,
             'identity_conflicts': 0, 'paused': False}
    if not local_only:
        limiter = AsyncTokenBucket(settings.openalex_rps)
        async with make_client() as client:
            for _ in range(batches):
                with session_factory() as session:
                    checkpoint = session.query(CrawlState).filter(CrawlState.scope_key == CURSOR_KEY).one_or_none()
                    try:
                        after = max(0, int(checkpoint.cursor)) if checkpoint else 0
                    except (ValueError, TypeError):
                        after = 0
                    targets = session.query(Paper.id, Paper.openalex_id, Paper.doi).filter(
                        Paper.id > after, or_(Paper.openalex_id.isnot(None), Paper.doi.isnot(None)),
                        or_(Paper.oa_url.is_(None), func.trim(Paper.oa_url) == ''),
                    ).order_by(Paper.id).limit(50).all()
                    if not targets:
                        if checkpoint:
                            checkpoint.cursor = '0'
                            session.commit()
                        break
                links, doi_links = {}, {}
                groups = [('openalex', [_openalex_key(oid) for _, oid, _ in targets if _openalex_key(oid)]),
                          ('doi', [_doi(doi) for _, oid, doi in targets if not _openalex_key(oid) and _doi(doi)])]
                for field, identifiers in groups:
                    identifiers = list(dict.fromkeys(value for value in identifiers if not re.search(r'[,|]', value)))
                    if not identifiers:
                        continue
                    await limiter.acquire()
                    response = await client.get('https://api.openalex.org/works', params={
                        'filter': field + ':' + '|'.join(identifiers), 'per-page': 50,
                        'select': 'id,doi,best_oa_location,open_access,primary_location,locations',
                        'mailto': settings.contact_email,
                    })
                    if response.status_code in (401, 403, 429):
                        stats['paused'] = True
                        log.warning('Link backfill paused: HTTP %d; cursor preserved', response.status_code)
                        break
                    response.raise_for_status()
                    payload = response.json()
                    values = payload.get('results') if isinstance(payload, dict) else None
                    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                        raise ValueError('Invalid OpenAlex response')
                    for item in values:
                        link = best_openalex_url(item)
                        returned_doi = _doi(item.get('doi'))
                        if key := _openalex_key(item.get('id')):
                            links[key] = (returned_doi, link)
                        if returned_doi:
                            doi_links[returned_doi] = link
                if stats['paused']:
                    break
                with session_factory() as session:
                    for paper_id, oid, doi in targets:
                        paper = session.get(Paper, paper_id)
                        if paper is None or safe_http_url(paper.oa_url):
                            continue
                        # Do not attach a different paper's OA URL through a stale OpenAlex ID.
                        if _openalex_key(oid):
                            returned_doi, link = links.get(_openalex_key(oid), (None, None))
                            if _doi(paper.doi) and returned_doi and _doi(paper.doi) != returned_doi:
                                stats['identity_conflicts'] += 1
                                continue
                        else:
                            link = doi_links.get(_doi(doi)) if _doi(paper.doi) == _doi(doi) else None
                        if link:
                            paper.oa_url = link
                            stats['openalex_filled'] += 1
                    checkpoint = session.query(CrawlState).filter(CrawlState.scope_key == CURSOR_KEY).one_or_none()
                    if checkpoint is None:
                        session.add(CrawlState(scope_key=CURSOR_KEY, cursor=str(targets[-1][0])))
                    else:
                        checkpoint.cursor = str(targets[-1][0])
                    session.commit()
                stats['checked'] += len(targets)
    with session_factory() as session:
        stats['remaining'] = session.query(Paper).filter(
            or_(Paper.oa_url.is_(None), func.trim(Paper.oa_url) == ''),
            or_(Paper.openalex_id.isnot(None), Paper.doi.isnot(None))).count()
    log.info('Link backfill result: %s', stats)
    return stats
