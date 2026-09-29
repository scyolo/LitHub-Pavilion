"""Link cached arXiv metadata to independently verified publisher inventories.

The arXiv page is only identity/abstract evidence, never acceptance evidence.
A unique same-venue publisher title AND complete author list must corroborate it.
"""
import argparse
import hashlib
import json
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.db import db_file_path
from app.models import Author, Paper, PaperAuthor, utcnow_iso
from app.services.paper_store import _add_authors, ccf_track_eligible
from app.services.publication_identity import publication_authors_match
from scripts.audit_publications import latest_entries, official_records
from scripts.reconcile_papers import _backup, _merge_one
from scripts.reconcile_publication_versions import compatible


class CitationMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name', '').startswith('citation_'):
            self.values.setdefault(values['name'], []).append(values.get('content', ''))


def reconcile_cached(path, inventories, fetched, *, apply=False):
    path = path.resolve()
    inventory = {}
    for (venue, year), entry in latest_entries(inventories, 'official-inventory-*.json', 'units',
                                              lambda row: (row.get('venue'), row.get('year'))).items():
        if not entry.get('inventory_complete'):
            continue
        for raw in official_records(entry, inventories):
            inventory.setdefault((venue, normalize_title(raw.title)), []).append(raw)
    report = {'started_at': utcnow_iso(), 'dry_run': not apply, 'changes': [], 'skipped': [], 'pdf_downloads': 0}
    if apply:
        report['backup'] = str(_backup(path))
    def connect():
        return sqlite3.connect(path.as_uri() + ('?mode=rw' if apply else '?mode=ro'), uri=True)
    from sqlalchemy import create_engine
    engine = create_engine('sqlite://', creator=connect)
    try:
        with Session(engine) as session:
            if apply:
                session.connection().exec_driver_sql('PRAGMA foreign_keys=ON')
            for entry in json.loads(fetched.read_text('utf-8')):
                file = Path(entry['cache'])
                paper = session.get(Paper, entry['id'])
                if not paper or not file.is_file():
                    continue
                metadata = CitationMetadata()
                metadata.feed(file.read_text('utf-8'))
                values = metadata.values
                if values.get('citation_arxiv_id') != [paper.arxiv_id] or len(values.get('citation_title', [])) != 1:
                    report['skipped'].append({'id': paper.id, 'reason': 'arXiv page identity mismatch'})
                    continue
                title = values['citation_title'][0]
                if normalize_title(title) != paper.title_norm:
                    report['skipped'].append({'id': paper.id, 'reason': 'stored/arXiv titles differ'})
                    continue
                candidates = [raw for raw in inventory.get((paper.venue.abbr, normalize_title(title)), [])
                              if publication_authors_match(values.get('citation_author', []), raw.authors)]
                if len(candidates) != 1:
                    report['skipped'].append({'id': paper.id, 'reason': 'publisher title/authors not uniquely corroborated'})
                    continue
                raw = candidates[0]
                official = session.query(Paper).filter(Paper.publisher_key == raw.extra['publisher_key']).one_or_none()
                if not official or official.id == paper.id or not compatible(paper, official):
                    report['skipped'].append({'id': paper.id, 'reason': 'missing or conflicting official record'})
                    continue
                canonical, duplicate = sorted((paper, official), key=lambda p: p.id)
                change = {'canonical': canonical.id, 'removed': duplicate.id, 'old_year': paper.year,
                          'year': raw.year, 'title': raw.title, 'publisher_key': raw.extra['publisher_key'],
                          'arxiv_id': paper.arxiv_id, 'arxiv_cache_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                          'previous_authors': [name for name, in session.query(Author.name).join(PaperAuthor).filter(PaperAuthor.paper_id == paper.id)]}
                report['changes'].append(change)
                if apply:
                    canonical.year = raw.year
                    canonical.publication_date = raw.publication_date
                    _merge_one(session, canonical, duplicate, authors_from=official)
                    session.query(PaperAuthor).filter(PaperAuthor.paper_id == canonical.id).delete(synchronize_session='fetch')
                    session.flush()
                    _add_authors(session, canonical.id, raw.authors, {})
                    canonical.title, canonical.title_norm = raw.title, normalize_title(raw.title)
                    canonical.venue_confirmed = int(ccf_track_eligible(raw, canonical.venue))
                    canonical.note = ((canonical.note + '\n') if canonical.note else '') + 'Reviewed arXiv identity against official publication: ' + change['publisher_key'] + '; arXiv ' + change['arxiv_id']
                    abstract = values.get('citation_abstract', [''])[0]
                    if not canonical.abstract and abstract:
                        canonical.abstract = abstract
            if apply:
                session.flush()
                assert session.connection().exec_driver_sql('PRAGMA quick_check').scalar() == 'ok'
                assert not session.connection().exec_driver_sql('PRAGMA foreign_key_check').all()
                for index in ('papers_fts', 'paper_titles_fts'):
                    exists = session.connection().exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name=?", (index,)).first()
                    if exists:
                        session.connection().exec_driver_sql(f"INSERT INTO {index}({index},rank) VALUES('integrity-check',1)")
                session.commit()
                report['integrity'] = 'ok'
    finally:
        engine.dispose()
    report['finished_at'] = utcnow_iso()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--inventories', type=Path, required=True)
    parser.add_argument('--fetched', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = reconcile_cached(args.database, args.inventories, args.fetched, apply=args.apply)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'dry_run': report['dry_run'], 'changes': len(report['changes']),
                      'skipped': len(report['skipped']), 'report': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
