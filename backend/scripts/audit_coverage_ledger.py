"""Reparse saved official evidence and compare identities with the public reader.

Read-only SQLite, no network, no collector lifecycle, no writes to the corpus.
A fully reconciled selected research list is NOT full venue/year/topic coverage.
"""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.filtering import PaperFilters, paper_query
from app.cleaning import normalize_title, author_name_norm, clean_author_name
from app.collectors.acm_proceedings import match_official_track
from app.db import db_file_path
from app.models import Author, Paper, PaperAuthor, PaperDirection, Direction, Venue
from app.services.publication_admission import admission_reason
from app.services.publication_identity import _tokens
from scripts import import_acm_research_tracks as tracks

# These are observed official scope adapters, not the complete venue catalogue.
ADAPTERS = {
    ('SIGIR', 2023): ('sigir2023-full.html', tracks.official_sigir2023),
    ('SIGIR', 2024): ('sigir2024-papers.jsonl', tracks.official_sigir),
    ('SIGIR', 2025): ('sigir2025-accepted.html', tracks.official_sigir2025),
    ('SIGIR', 2026): ('sigir2026-home.html', tracks.official_sigir2026),
    ('WSDM', 2023): ('wsdm2023-accepted.html', tracks.official_wsdm2023),
    ('WSDM', 2024): ('wsdm2024-papers.html', tracks.official_wsdm),
    ('WSDM', 2025): ('wsdm2025-accepted.html', tracks.official_wsdm2025),
    ('WSDM', 2026): ('wsdm2026-accepted.html', tracks.official_wsdm2026),
    ('WWW', 2023): ('www2023-research.csv', tracks.official_www2023),
    ('WWW', 2024): ('www2024-research.html', tracks.official_www),
    ('WWW', 2026): ('www2026-research.html', tracks.official_www2026),
    ('ACM MM', 2024): ('mm2024-accepted-chunk.txt', tracks.official_mm),
    ('CIKM', 2025): ('cikm2025-accepted.html', tracks.official_cikm2025),
}


def compare_unit(db, venue, year, records, unresolved):
    by_doi = {paper.doi: paper for paper in db.query(Paper).filter(Paper.venue_id == venue.id, Paper.year == year)}
    names = defaultdict(list)
    for pid, name in (db.query(PaperAuthor.paper_id, Author.name).join(Author).join(Paper, Paper.id == PaperAuthor.paper_id)
                      .filter(Paper.venue_id == venue.id, Paper.year == year)):
        names[pid].append(name)
    matched, missing = [], []
    for raw in records:
        paper = by_doi.get(raw.doi)
        reason = None
        if paper is None:
            reason = 'not_in_venue_year_database'
        elif admission_reason(paper, venue):
            reason = 'not_publicly_admitted'
        elif paper.title_norm != normalize_title(raw.title):
            reason = 'title_identity_mismatch'
        elif (not names[paper.id] or not raw.authors
              or (Counter(tuple(sorted(_tokens(n))) for n in names[paper.id]) != Counter(tuple(sorted(_tokens(n))) for n in raw.authors)
                  and Counter(author_name_norm(clean_author_name(n)) for n in names[paper.id]) != Counter(author_name_norm(clean_author_name(n)) for n in raw.authors))):
            reason = 'author_identity_mismatch'
        if reason:
            missing.append({'doi': raw.doi, 'title': raw.title, 'reason': reason})
        else:
            matched.append(paper.id)
    return {'official_count': len(records) + len(unresolved), 'cross_source_identity_matches': len(records),
            'public_identity_matches': len(matched), 'matched_ids': matched,
            'official_unresolved': unresolved, 'missing_or_conflicting': missing,
            'official_scope_identity_complete': bool(records) and not unresolved and not missing,
            'full_venue_year_coverage_verified': False}


def build_ledger(database, evidence, years):
    database = database.resolve()
    if not database.is_file():
        raise ValueError('Existing database required')
    def connect():
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        connection.execute('PRAGMA query_only=ON')
        return connection
    engine = create_engine('sqlite://', creator=connect)
    units = []
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql('BEGIN')
            venues = db.query(Venue).filter(Venue.active == 1, Venue.ccf_level.in_(('A', 'B'))).all()
            public = paper_query(db, PaperFilters())
            totals, absent_abstracts, untagged = Counter(), Counter(), Counter()
            tagged = {pid for pid, in db.query(PaperDirection.paper_id).join(Direction).filter(Direction.enabled == 1)}
            for paper in public.yield_per(1000):
                key = (paper.venue_id, paper.year)
                totals[key] += 1
                absent_abstracts[key] += not bool((paper.abstract or '').strip())
                untagged[key] += paper.id not in tagged
            for venue in venues:
                for year in years:
                    key = (venue.id, year)
                    unit = {'venue': venue.abbr, 'year': year, 'configured_level': venue.ccf_level,
                            'public_records': totals[key], 'missing_abstracts': absent_abstracts[key],
                            'without_enabled_topic': untagged[key], 'full_venue_year_coverage_verified': False,
                            'selected_research_scope': None,
                            'evidence_status': 'not_audited_by_this_acm_ledger'}
                    if (venue.abbr, year) in ADAPTERS:
                        filename, parse = ADAPTERS[(venue.abbr, year)]
                        inventory_file = evidence / f"inventory-{venue.abbr.replace(' ', '_')}-{year}.json"
                        try:
                            inventory = json.loads(inventory_file.read_text('utf8'))
                            records, unresolved = match_official_track(inventory, parse(evidence))
                            unit['selected_research_scope'] = compare_unit(db, venue, year, records, unresolved)
                            unit['source_file'] = filename
                            unit['source_sha256'] = hashlib.sha256((evidence / filename).read_bytes()).hexdigest()
                            unit['publisher_inventory_sha256'] = hashlib.sha256(inventory_file.read_bytes()).hexdigest()
                            unit['evidence_status'] = 'reparsed_and_compared_to_current_database'
                        except (OSError, ValueError, KeyError) as exc:
                            unit['evidence_status'] = 'evidence_invalid_or_unavailable'
                            unit['error'] = str(exc)
                    units.append(unit)
            assert db.connection().exec_driver_sql('PRAGMA query_only').scalar() == 1
    finally:
        engine.dispose()
    compared = [u for u in units if u['selected_research_scope'] is not None]
    return {'created_at': datetime.now(timezone.utc).isoformat(), 'read_only': True, 'network_requests': 0,
            'years': list(years), 'configured_sources': len(venues), 'source_year_units': len(units),
            'reparsed_official_scope_units': len(compared),
            'scope_expected_records': sum(u['selected_research_scope']['official_count'] for u in compared),
            'scope_public_identity_matches': sum(u['selected_research_scope']['public_identity_matches'] for u in compared),
            'scope_unresolved': sum(len(u['selected_research_scope']['official_unresolved']) for u in compared),
            'matched_but_missing_or_conflicting': sum(len(u['selected_research_scope']['missing_or_conflicting']) for u in compared),
            'units': units, 'full_coverage_verified': False,
            'limitations': ['Other collector evidence is not evaluated by this ACM ledger; not audited does not mean no evidence exists.',
                           'Configured grades are not independently certified CCF grades.',
                           'Complete selected list does not prove all eligible tracks or all topics covered.',
                           'Missing abstract/untagged counts flag review needs, not proof of topic irrelevance.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--year-from', type=int, default=2023)
    parser.add_argument('--year-to', type=int, default=2026)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 2000 <= args.year_from <= args.year_to <= 2100:
        parser.error('Invalid year interval')
    report = build_ledger(args.database, args.evidence, range(args.year_from, args.year_to + 1))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('units', 'limitations')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
