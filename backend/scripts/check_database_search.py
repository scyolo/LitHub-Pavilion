"""Verify real backend search against saved snapshot samples, strictly read-only.

Does not start the API lifespan, collectors or scheduler. Use the same sample
report produced by frontend/scripts/check-snapshot-search.js for parity checks.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from app.api.filtering import PaperFilters, paper_query
from app.api.routers.search import _build_match_expr, search
from app.cleaning import normalize_title
from app.db import db_file_path
from app.models import Paper


def check_search(path, samples, *, expected_count=None):
    path = path.resolve()
    if not path.is_file() or not samples:
        raise ValueError('An existing SQLite database and nonempty search samples are required')

    def connect():
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        connection.execute('PRAGMA query_only=ON')
        return connection

    engine = create_engine('sqlite://', creator=connect)
    results = []
    and_checks = 0
    started = perf_counter()
    try:
        with Session(engine) as session:
            stored_count = session.query(func.count(Paper.id)).scalar()
            public = paper_query(session, PaperFilters())
            count = public.count()
            if expected_count is not None and count != expected_count:
                raise ValueError('Snapshot sample report is stale: database paper count differs')
            all_title_checks = 0
            title_errors = []
            for pid, title, stored_norm in public.with_entities(Paper.id, Paper.title, Paper.title_norm).yield_per(1000):
                normalized = normalize_title(title)
                if stored_norm != normalized:
                    title_errors.append({'id': pid, 'reason': 'stale normalized title'})
                    continue
                try:
                    _build_match_expr(title, exact_title=True)
                except Exception as exc:
                    title_errors.append({'id': pid, 'reason': str(exc)})
                    continue
                # Exercise the same indexed exact-title recall branch for every
                # identity; full API ordering/FTS parity is checked below.
                found = session.connection().exec_driver_sql(
                    'SELECT id FROM papers WHERE title_norm=? AND id=?', (normalized, pid)).first()
                if found is None:
                    title_errors.append({'id': pid, 'reason': 'exact-title identity absent'})
                else:
                    all_title_checks += 1
            assert not title_errors, str(title_errors[:20])
            assert all_title_checks == count
            for sample in samples:
                title = sample['title']
                result = search(q=title, filters=PaperFilters(), sort='relevance', page=1, size=100, db=session, match='exact')
                assert result['items'], f"No full-title result for {sample['id']}"
                assert normalize_title(result['items'][0]['title']) == normalize_title(title), f"Exact title not first: {sample['id']}"
                assert any(p['id'] == sample['id'] for p in result['items']), f"Expected identity missing: {sample['id']}"
                results.append({'id': sample['id'], 'title': title, 'matches': result['total']})
                tokens = normalize_title(title).split()
                if and_checks < 16 and len(tokens) >= 6 and title.isascii():
                    query = ' '.join([tokens[0], tokens[len(tokens)//2], tokens[-1]])
                    scattered = search(q=query, filters=PaperFilters(venue=sample['venue'],year=sample['year']),
                                       sort='relevance',page=1,size=100,db=session)
                    assert any(p['id'] == sample['id'] for p in scattered['items']), f"Non-adjacent AND recall failed: {sample['id']}"
                    and_checks += 1
            query_only = session.connection().exec_driver_sql('PRAGMA query_only').scalar()
            assert query_only == 1
    finally:
        engine.dispose()
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'database': str(path),
            'read_only': True, 'query_only': True, 'api_lifespan_started': False, 'network_requests': 0,
            'paper_count': count, 'stored_record_count': stored_count, 'all_title_identity_checks': all_title_checks, 'all_titles_queryable': all_title_checks == count,
            'exact_title_checks': len(results), 'non_adjacent_and_checks': and_checks,
            'elapsed_ms': round((perf_counter()-started)*1000), 'samples': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    samples = json.loads(args.samples.read_text(encoding='utf-8-sig'))
    report = check_search(args.database, samples['samples'], expected_count=samples['paper_count'])
    report['snapshot_revision'] = samples['revision']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'samples'},ensure_ascii=False))


if __name__ == '__main__':
    main()
