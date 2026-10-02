"""Recover official SIGIR 2023/2024/2025 abstracts, preserving existing text and private candidates."""
import argparse
import hashlib
import html
from urllib.parse import urlsplit, parse_qs
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
    # This observed page contains only 100 entries, NOT the whole proceedings.
    2025: ('3726302', 100, 'SIGIR 2025', 'https://sigir2025.dei.unipd.it/proceedings.html'),
    2023: ('3539618', 469, 'SIGIR | Taipei | Taiwan | 2023', 'https://sigir.org/sigir2023/program/proceedings/'),
    2024: ('3626772', 389, 'SIGIR 2024', 'https://sigir-2024.github.io/proceedings.html'),
}


def parse_page(text, *, year=2024):
    if year not in EDITIONS:
        raise ValueError('Unsupported SIGIR proceedings edition')
    parent, count, marker, _ = EDITIONS[year]
    if marker not in text or parent not in text:
        raise ValueError('SIGIR 2024 proceedings identity mismatch')
    rows = []
    for block in re.split(r'(?=<h3>)', text)[1:]:
        link = re.search(r'<a class="DLtitleLink"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        authors = re.search(r'<ul class="DLauthors">(.*?)</ul>', block, re.S)
        abstract = re.search(r'<div class="DLabstract">\s*<div[^>]*>(.*?)</div>', block, re.S)
        if not (link and authors and abstract):
            raise ValueError('Incomplete SIGIR publication block')
        # Read the embedded DOI string on the official catalogue only. Never
        # fetch or trust the redirect wrapper as a publication identity.
        target = html.unescape(link[1])
        if year == 2025:
            wrapper = urlsplit(target)
            if wrapper.scheme != 'https' or wrapper.hostname != 'www.google.com' or wrapper.path != '/url':
                raise ValueError('Unexpected SIGIR 2025 link wrapper')
            targets = parse_qs(wrapper.query).get('q', [])
            if len(targets) != 1 or not re.fullmatch(rf'https://dl\.acm\.org/doi/10\.1145/{parent}\.\d+', targets[0]):
                raise ValueError('Invalid explicit ACM publication target')
            target = targets[0]
        doi = re.search(rf'https://dl\.acm\.org/doi/(10\.1145/{parent}\.\d+)(?:__|$)', target)
        if not doi:
            raise ValueError('Unknown ACM identity or parent proceedings')
        rows.append({'doi': doi[1], 'title': plain(link[2]),
                     'authors': [plain(name) for name in re.findall(r'<li[^>]*>(.*?)</li>', authors[1], re.S)],
                     'abstract': plain(abstract[1])})
    if len(rows) != count or len({row['doi'] for row in rows}) != count:
        raise ValueError('SIGIR proceedings changed or truncated')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--year', type=int, choices=sorted(EDITIONS), default=2024)
    args = parser.parse_args()
    source = args.evidence / f'sigir{args.year}-proceedings.html'
    rows = parse_page(source.read_text('utf8'), year=args.year)
    path = args.database.resolve()
    if not path.is_file():
        parser.error('Existing database required')
    report = {'official_url': EDITIONS[args.year][3], 'year': args.year,
              'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'apply': args.apply,
              'new_papers': 0, 'parsed_abstracts': len(rows), 'full_proceedings_coverage_verified': False}
    if args.apply:
        report['backup'] = str(_backup(path))
    engine = _make_engine('sqlite:///' + path.as_posix())
    try:
        with Session(engine) as db:
            venue = db.query(Venue).filter(Venue.abbr == 'SIGIR').one()
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
    name = f'sigir{args.year}-abstracts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'
    (args.evidence / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': name, 'filled_or_proposed': len(report['filled']), 'rejected': len(report['rejected']), 'apply': args.apply}))


if __name__ == '__main__':
    main()
