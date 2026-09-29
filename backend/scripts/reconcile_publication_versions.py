"""Reconcile verified publication/preprint versions; preserve ids, links and manual tags.

Never merge two different official DOI/DBLP/OpenAlex/arXiv identities. Cross-year
matching requires an official volume, equal full titles AND uniquely matched
complete author lists; initials need a full-name anchor or a shared identifier.
"""
import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.cleaning import normalize_arxiv_id
from app.db import _make_engine, db_file_path
from app.models import Author, Paper, PaperAuthor, utcnow_iso
from scripts.reconcile_papers import _backup, _merge_one
from app.services.paper_store import is_repository_doi
from app.services.publication_identity import preprint_id, publication_authors_match


def has_evidence(paper):
    return bool(paper.publisher_key or 'Verified publisher metadata: Crossref DOI ' in (paper.note or ''))


def compatible(first, second):
    for field in ('dblp_key', 'openalex_id', 'arxiv_id', 's2_id', 'publisher_key'):
        a, b = getattr(first, field), getattr(second, field)
        if a and b and a != b:
            return False
    aid_a, aid_b = preprint_id(first), preprint_id(second)
    if aid_a and aid_b and aid_a != aid_b:
        return False
    return not (first.doi and second.doi and first.doi != second.doi and not is_repository_doi(first.doi) and not is_repository_doi(second.doi))


def reconcile_versions(path, restore_from=None, *, dry_run=False):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('An existing database is required')
    if dry_run:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix='lithub-version-preview-') as temporary:
            copy_path = Path(temporary) / 'papers.db'
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(copy_path)) as copy:
                source.backup(copy)
            report = reconcile_versions(copy_path, restore_from)
            report.update(database=str(path), dry_run=True, backup=None)
            return report
    report = {'started_at': utcnow_iso(), 'database': str(path), 'dry_run': False, 'backup': str(_backup(path)), 'merged': [], 'arxiv_restored': [], 'skipped': [], 'pdf_downloads': 0}
    engine = _make_engine('sqlite:///' + path.as_posix())
    try:
        with Session(engine) as session:
            def restore(aid, candidates, reason):
                if not aid or len(candidates) != 1:
                    return
                paper = candidates[0]
                if paper.arxiv_id:
                    return
                owner = session.query(Paper.id).filter(Paper.arxiv_id == aid).first()
                if owner:
                    report['skipped'].append({'ids': [paper.id, owner[0]], 'reason': 'arxiv ID already owned'})
                    return
                paper.arxiv_id = aid
                report['arxiv_restored'].append({'id': paper.id, 'arxiv_id': aid, 'reason': reason})
            for paper in session.query(Paper).filter(Paper.doi.like('10.48550/arxiv.%'), Paper.arxiv_id.is_(None)).all():
                restore(normalize_arxiv_id(paper.doi.removeprefix('10.48550/arxiv.')), [paper], 'repository DOI')
            if restore_from:
                with sqlite3.connect(restore_from.as_uri() + '?mode=ro', uri=True) as original:
                    for old in original.execute("SELECT id,dblp_key,openalex_id,doi,arxiv_id FROM papers WHERE doi LIKE '10.48550/arxiv.%' OR arxiv_id IS NOT NULL"):
                        aid = normalize_arxiv_id(old[4]) or normalize_arxiv_id((old[3] or '').removeprefix('10.48550/arxiv.'))
                        keys = []
                        if old[1]: keys.append(Paper.dblp_key == old[1])
                        if old[2]: keys.append(Paper.openalex_id == old[2])
                        if keys:
                            restore(aid, session.query(Paper).filter(or_(*keys)).all(), 'pre-reconciliation backup strong ID')
            session.flush()
            author_names = {}
            for pid, name in session.query(PaperAuthor.paper_id, Author.name).join(Author, Author.id == PaperAuthor.author_id).order_by(PaperAuthor.paper_id, PaperAuthor.author_order):
                author_names.setdefault(pid, []).append(name)
            groups = session.query(Paper.venue_id, Paper.title_norm).group_by(Paper.venue_id, Paper.title_norm).having(func.count(Paper.id) > 1).all()
            for venue_id, title in groups:
                rows = session.query(Paper).filter(Paper.venue_id == venue_id, Paper.title_norm == title).all()
                # A DOI-verified legacy row can duplicate a unique catalogue row.
                # Prefer the catalogue anchor; compatible() still rejects distinct IDs.
                official = [p for p in rows if p.publisher_key]
                if not official:
                    official = [p for p in rows if has_evidence(p)]
                if len(official) != 1:
                    continue
                published = official[0]
                for other in sorted((p for p in rows if p.id != published.id), key=lambda p: p.id):
                    reason = None
                    shared = bool(preprint_id(other) and preprint_id(other) == preprint_id(published))
                    if not compatible(published, other): reason = 'distinct strong identities'
                    elif not publication_authors_match(author_names.get(other.id, []), author_names.get(published.id, []), shared_identity=shared): reason = 'author lists differ or are ambiguous'
                    elif other.year != published.year and other.doi and not is_repository_doi(other.doi):
                        suffix = re.search(r'(\d{2})[a-z]?$', other.dblp_key or '')
                        if not suffix or int(suffix[1]) != published.year % 100:
                            reason = 'formal DOI across years without matching DBLP year evidence'
                    if reason:
                        report['skipped'].append({'ids': [published.id, other.id], 'reason': reason})
                        continue
                    canonical, duplicate = sorted((published, other), key=lambda p: p.id)
                    year, date, title = published.year, published.publication_date, published.title
                    confirmed = published.venue_confirmed
                    old_year = canonical.year
                    record = {'canonical': canonical.id, 'removed': duplicate.id, 'title': title, 'old_year': old_year, 'year': year,
                              'author_evidence': 'unique complete author match', 'shared_arxiv': shared}
                    if canonical.year != year:
                        canonical.publication_date = None
                    canonical.year = year
                    published_authors = author_names[published.id]
                    _merge_one(session, canonical, duplicate, authors_from=published)
                    if canonical.title != title:
                        canonical.note = ((canonical.note + '\n') if canonical.note else '') + 'Previous indexed title: ' + canonical.title
                        canonical.title = title
                    canonical.publication_date = date
                    canonical.venue_confirmed = confirmed
                    author_names[canonical.id] = published_authors
                    report['merged'].append(record)
                    published = canonical
            session.flush()
            report['paper_count'] = session.query(func.count(Paper.id)).scalar()
            report['quick_check'] = session.connection().exec_driver_sql('PRAGMA quick_check').scalar()
            report['foreign_key_errors'] = [list(r) for r in session.connection().exec_driver_sql('PRAGMA foreign_key_check')]
            session.connection().exec_driver_sql("INSERT INTO papers_fts(papers_fts, rank) VALUES('integrity-check', 1)")
            report['fts_integrity'] = 'ok'
            if report['quick_check'] != 'ok' or report['foreign_key_errors']:
                raise RuntimeError('Publication reconciliation failed integrity checks')
            session.commit()
            report['counts'] = {'merged': len(report['merged']), 'arxiv_restored': len(report['arxiv_restored']), 'years_corrected': sum(r['old_year'] != r['year'] for r in report['merged']), 'skipped': len(report['skipped'])}
    finally:
        engine.dispose()
    report['finished_at'] = utcnow_iso()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--restore-from', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Reconcile a disposable copy; never change the source database')
    parser.add_argument('--output', type=Path, default=Path('artifacts') / ('publication-audit-' + datetime.now(timezone.utc).strftime('%Y%m%d')))
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    report = reconcile_versions(args.database.resolve(), args.restore_from.resolve() if args.restore_from else None, dry_run=args.dry_run)
    target = args.output / ('version-reconcile-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(target.resolve()), 'counts': report['counts'], 'paper_count': report['paper_count'], 'quick_check': report['quick_check']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
