"""Short single-writer transactions for parallel source API maintenance jobs."""
from collections import Counter
from sqlalchemy import text
from app.cleaning import normalize_doi
from app.models import Paper
from app.services.publisher_metadata import apply_items
from app.services.tagging import apply_tagging


def apply_catalog_page(session, items, years, rules, thresholds):
    totals, conflicts = Counter(), []
    for offset in range(0, len(items), 100):
        batch = items[offset:offset + 100]
        # Callers hold only read state. Acquire the writer before identity reads
        # to avoid WAL's non-retryable read-to-write snapshot upgrade race.
        session.rollback()
        session.execute(text('PRAGMA busy_timeout=120000'))
        session.commit()
        try:
            session.execute(text('BEGIN IMMEDIATE'))
            result = apply_items(session, batch, years, commit=False)
            dois = [normalize_doi(item.get('DOI')) for item in batch]
            # Re-tag existing identities too: an interrupted older maintenance
            # run may have committed a paper before adding its direction labels.
            for paper in session.query(Paper).filter(Paper.doi.in_(dois)).all():
                apply_tagging(session, paper.id, paper.title, paper.abstract, rules, thresholds)
            session.commit()
            totals.update(result['counts']); conflicts.extend(result['conflicts'])
        except Exception:
            session.rollback()
            raise
    return {'counts': dict(totals), 'conflicts': conflicts}
