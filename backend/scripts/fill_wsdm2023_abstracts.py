"""Recover official WSDM 2023/2024 abstracts, preserving existing text and private candidates."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session
from app.db import _make_engine, db_file_path
from app.models import Paper, Venue
from app.services.official_abstracts import fill_verified_abstracts
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.import_acm_research_tracks import plain
from scripts.reconcile_papers import _backup


EDITIONS = {
    2023: ('3539597', 187, 'Sixteenth ACM International Conference on Web Search and Data Mining',
           'https://www.wsdm-conference.org/2023/program/acm-proceedings'),
    2024: ('3616855', 175, 'WSDM', 'https://www.wsdm-conference.org/2024/acm-proceedings/'),
}


def parse_page(text, *, year=2023):
    if year not in EDITIONS:
        raise ValueError('Unsupported verified WSDM edition')
    parent, expected_count, marker, _ = EDITIONS[year]
    if parent not in text or marker not in text or (year == 2024 and '2024' not in text):
        raise ValueError('Official proceedings identity mismatch')
    rows = []
    for block in re.split(r'(?=<h3>)', text)[1:]:
        link = re.search(rf'<a class="DLtitleLink"[^>]*href="https://dl.acm.org/doi/(10\.1145/{parent}\.\d+)"[^>]*>(.*?)</a>', block, re.S)
        authors = re.search(r'<ul class="DLauthors">(.*?)</ul>', block, re.S)
        abstract = re.search(r'<div class="DLabstract">\s*<div[^>]*>(.*?)</div>', block, re.S)
        if link and authors and abstract:
            rows.append({'doi': link[1], 'title': plain(link[2]),
                         'authors': [plain(name) for name in re.findall(r'<li[^>]*>(.*?)</li>', authors[1], re.S)],
                         'abstract': plain(abstract[1])})
    if len(rows) != expected_count or len({row['doi'] for row in rows}) != expected_count:
        raise ValueError('Official abstract inventory changed or truncated')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--year', type=int, choices=sorted(EDITIONS), default=2023)
    args = parser.parse_args()
    source = args.evidence / f'wsdm{args.year}-proceedings.html'
    rows = parse_page(source.read_text('utf8'), year=args.year)
    path = args.database.resolve()
    if not path.is_file():
        parser.error('Existing database required')
    report = {'official_url': EDITIONS[args.year][3], 'year': args.year,
              'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'apply': args.apply,
              'new_papers': 0, 'parsed_abstracts': len(rows)}
    if args.apply:
        report['backup'] = str(_backup(path))
    engine = _make_engine('sqlite:///' + path.as_posix())
    try:
        with Session(engine) as db:
            venue = db.query(Venue).filter(Venue.abbr == 'WSDM').one()
            report.update(fill_verified_abstracts(db, rows, venue.id, args.year))
            if args.apply:
                rules, thresholds = load_rules(db), load_thresholds(db)
                for paper in db.query(Paper).filter(Paper.id.in_(report['filled'])):
                    apply_tagging(db, paper.id, paper.title, paper.abstract, rules, thresholds)
                db.commit()
            else:
                db.rollback()
    finally:
        engine.dispose()
    name = f'wsdm{args.year}-abstracts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'
    (args.evidence / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': name, 'filled_or_proposed': len(report['filled']), 'rejected': len(report['rejected']), 'apply': args.apply}))


if __name__ == '__main__':
    main()
