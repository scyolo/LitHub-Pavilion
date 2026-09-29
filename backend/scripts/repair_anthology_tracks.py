"""Correct existing off-main Anthology years without declaring main-track acceptance."""
import argparse
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.cleaning import normalize_doi, normalize_title
from app.collectors.crossref import item_to_raw
from app.db import _make_engine, db_file_path
from app.models import Paper, utcnow_iso
from scripts.reconcile_papers import _backup


def repair_existing(path, cache, *, apply=False):
    records = {}
    for line in cache.read_text('utf-8').splitlines():
        if line:
            item = json.loads(line)
            records[normalize_doi(item.get('DOI'))] = item
    report = {'started_at': utcnow_iso(), 'dry_run': not apply, 'changes': [], 'conflicts': [], 'pdf_downloads': 0}
    if apply:
        report['backup'] = str(_backup(path))
    engine = _make_engine('sqlite:///' + path.resolve().as_posix())
    try:
        with Session(engine) as session:
            for paper in session.query(Paper).filter(Paper.doi.like('10.18653/%')).all():
                item = records.get(paper.doi)
                raw = item_to_raw(item) if item else None
                if not raw or paper.publisher_key:
                    continue
                container = ' '.join(item.get('container-title') or [])
                match = re.fullmatch(r'10\.18653/v1/(20\d{2})\.findings-(acl|emnlp)\.\d+', paper.doi)
                if not match or 'Findings of the Association for Computational Linguistics:' not in container:
                    continue
                if paper.venue.abbr != match[2].upper() or raw.year != int(match[1]) or str(raw.year) not in container:
                    report['conflicts'].append({'id': paper.id, 'reason': 'venue/date/container mismatch'})
                    continue
                if normalize_title(raw.title) != paper.title_norm:
                    report['conflicts'].append({'id': paper.id, 'reason': 'publisher title mismatch'})
                    continue
                note = 'Publisher track evidence: ' + container + '; DOI ' + paper.doi + '; not verified as the main CCF proceedings'
                if paper.year == raw.year and not paper.venue_confirmed and note in (paper.note or ''):
                    continue
                report['changes'].append({'id': paper.id, 'old_year': paper.year, 'year': raw.year,
                                          'was_confirmed': bool(paper.venue_confirmed), 'doi': paper.doi, 'container': container})
                if apply:
                    if paper.year != raw.year:
                        paper.year = raw.year
                        paper.publication_date = raw.publication_date
                    paper.venue_confirmed = 0
                    if note not in (paper.note or ''):
                        paper.note = ((paper.note + '\n') if paper.note else '') + note
            if apply:
                session.flush()
                assert session.connection().exec_driver_sql('PRAGMA quick_check').scalar() == 'ok'
                assert not session.connection().exec_driver_sql('PRAGMA foreign_key_check').all()
                session.connection().exec_driver_sql("INSERT INTO papers_fts(papers_fts,rank) VALUES('integrity-check',1)")
                session.commit()
    finally:
        engine.dispose()
    report['year_corrections'] = sum(r['old_year'] != r['year'] for r in report['changes'])
    report['confirmation_corrections'] = sum(r['was_confirmed'] for r in report['changes'])
    report['finished_at'] = utcnow_iso()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = repair_existing(args.database, args.cache, apply=args.apply)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('changes', 'conflicts')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
