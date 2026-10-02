"""Repair duplicate author positions using exact publisher identity evidence.

Default dry-run. Apply backs up and changes author_order only, never author IDs,
publication admission, metadata or topic labels. Unmatched identities stay put.
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.cleaning import normalize_title
from app.collectors.crossref import identify_venue, item_to_raw
from app.db import db_file_path
from app.services.author_order_repair import plan_author_order
from scripts.reconcile_papers import _backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    path = args.database.resolve()
    if not path.is_file():
        parser.error('Existing database required')
    report = {'applied': args.apply, 'changed': [], 'unresolved': [], 'plans': []}
    if args.apply:
        report['backup'] = str(_backup(path))
    db = sqlite3.connect(path if args.apply else path.as_uri() + '?mode=ro', uri=not args.apply)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE' if args.apply else 'BEGIN')
        ids = [row[0] for row in db.execute('SELECT DISTINCT paper_id FROM paper_authors GROUP BY paper_id,author_order HAVING count(*)>1')]
        report['conflicting_papers_before'] = len(ids)
        for pid in ids:
            file = args.evidence / 'author-order-crossref' / f'{pid}.json'
            try:
                evidence = file.read_bytes()
                item = json.loads(evidence)
                paper = db.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone()
                venue = SimpleNamespace(**dict(db.execute('SELECT * FROM venues WHERE id=?', (paper['venue_id'],)).fetchone()))
                raw = item_to_raw(item)
                if (not raw or raw.doi != paper['doi'] or raw.year != paper['year']
                        or normalize_title(raw.title) != paper['title_norm']
                        or identify_venue(item, {venue.abbr: venue}) is None):
                    raise ValueError('Publisher DOI/title/year/container mismatch')
                stored = [tuple(row) for row in db.execute('SELECT pa.author_id,a.name,pa.author_order FROM paper_authors pa JOIN authors a ON a.id=pa.author_id WHERE pa.paper_id=? ORDER BY pa.author_order,pa.author_id', (pid,))]
                planned = plan_author_order(stored, raw.authors)
                unit = {'paper_id': pid, 'doi': raw.doi, 'source_sha256': hashlib.sha256(evidence).hexdigest(),
                        'before': stored, 'after': planned}
                report['plans'].append(unit)
                if args.apply:
                    for aid, order in planned:
                        cursor = db.execute('UPDATE paper_authors SET author_order=? WHERE paper_id=? AND author_id=?', (order, pid, aid))
                        if cursor.rowcount != 1:
                            raise RuntimeError('Author relationship changed during repair')
                    report['changed'].append(pid)
            except (OSError, ValueError, KeyError) as exc:
                report['unresolved'].append({'paper_id': pid, 'reason': str(exc)})
        report['remaining_conflict_groups'] = db.execute('SELECT count(*) FROM (SELECT paper_id,author_order FROM paper_authors GROUP BY paper_id,author_order HAVING count(*)>1)').fetchone()[0]
        if args.apply:
            if db.execute('PRAGMA foreign_key_check').fetchall() or db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database integrity failure')
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    output = args.evidence / ('author-order-repair-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'applied': args.apply, 'verified_plans': len(report['plans']), 'changed': len(report['changed']), 'unresolved': len(report['unresolved']), 'remaining_conflict_groups': report['remaining_conflict_groups']}))


if __name__ == '__main__':
    main()
