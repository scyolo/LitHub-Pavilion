"""Cross-check saved official research lists, optionally import identity matches.

Default is audit-only. --apply backs up SQLite and preserves unmatched evidence.
"""
import argparse
import hashlib
from datetime import datetime, timezone
import html
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session
from app.collectors.acm_proceedings import match_official_track
from app.cleaning import normalize_title
from app.db import _make_engine, db_file_path
from app.models import Paper, Venue
from app.services.publisher_import import apply_records
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.reconcile_papers import _backup


def plain(value):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', value)).split())


def official_sigir(directory):
    rows = [json.loads(line) for line in (directory / 'sigir2024-papers.jsonl').read_text('utf8').splitlines() if line.strip()]
    full = [row for row in rows if row['submssion_id'].startswith('fp')]
    if len(full) != 160 or len({row['submssion_id'] for row in full}) != 160:
        raise ValueError('SIGIR 2024 full-paper official list is truncated or changed')
    return [{'title': row['title'], 'authors': [a['name'] for a in row['authors']]} for row in full]


def official_wsdm(directory):
    text = (directory / 'wsdm2024-papers.html').read_text('utf8')
    if 'The 17th ACM International WSDM Conference' not in text or '10.1145/3616855' not in text:
        raise ValueError('WSDM 2024 page identity mismatch')
    entries = []
    for title, authors in re.findall(r'<strong>(.*?)</strong>(.*?)(?=<strong>|</div>)', text, re.S):
        title = plain(title)
        if title == 'The proceedings are now available.':
            continue
        authors = plain(authors)
        depth, outside = 0, []
        for char in authors:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth < 0:
                    raise ValueError('Unbalanced author affiliation')
            elif depth == 0:
                outside.append(char)
        if depth:
            raise ValueError('Truncated author affiliation')
        names = [name.replace('*', '').strip() for name in ''.join(outside).split(';')]
        entries.append({'title': title, 'authors': names})
    if len(entries) != 109:
        raise ValueError('WSDM 2024 accepted-paper list is truncated or changed')
    return entries


def official_mm(directory):
    """Extract literal data from the observed official Vue chunk, never eval JS."""
    import ast
    text = (directory / 'mm2024-accepted-chunk.txt').read_text('utf8')
    if 'mainTitle:"Accepted Papers"' not in text:
        raise ValueError('ACM MM accepted-list identity mismatch')
    pattern = r'''\{type:"(paperTitle|paperAuthor)",text:("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\}'''
    parts = [(kind, json.loads(value) if value.startswith('"') else ast.literal_eval(value))
             for kind, value in re.findall(pattern, text)]
    if len(parts) != 2302 or text.count('type:"paperTitle"') != 1151 or text.count('type:"paperAuthor"') != 1151:
        raise ValueError('ACM MM 2024 accepted-list count changed or truncated')
    result, seen = [], set()
    for i in range(0, len(parts), 2):
        title, authors = parts[i:i + 2]
        if title[0] != 'paperTitle' or authors[0] != 'paperAuthor':
            raise ValueError('ACM MM title/author pairing mismatch')
        value = plain(title[1])
        match = re.fullmatch(r'(\d+)\s+(.+)', value)
        if not match or match[1] in seen:
            raise ValueError('ACM MM missing/duplicate submission identity')
        seen.add(match[1])
        names = [plain(name) for name in authors[1].split(',')]
        if not names or not all(names):
            raise ValueError('ACM MM missing author')
        result.append({'title': match[2], 'authors': names})
    return result


def official_www(directory):
    text = (directory / 'www2024-research.html').read_text('utf8')
    if not all(value in text for value in ('Research Tracks', 'The Web Conference 2024', '10.1145/3589334')):
        raise ValueError('WWW 2024 research-list identity mismatch')
    parts = re.findall(r'<div class="card-title"><strong>(.*?)</strong></div>\s*<p class="m-0 p-0">(.*?)</p>', text, re.S)
    if len(parts) != 405 or text.count('class="card-title"') != 405:
        raise ValueError('WWW 2024 research-list count changed or truncated')
    return [{'title': plain(title), 'authors': [plain(name) for name in authors.split(',')]}
            for title, authors in parts]


def official_www2023(directory):
    import csv
    with (directory / 'www2023-research.csv').open(encoding='utf8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['track', 'track name', 'title', 'authors']:
            raise ValueError('WWW 2023 CSV header mismatch')
        rows = list(reader)
    if len(rows) != 367 or any(not row['track'].isdigit() or not row['title'] or not row['authors'] for row in rows):
        raise ValueError('WWW 2023 research-list count changed or truncated')
    return [{'title': row['title'], 'authors': [name.strip() for name in re.split(r',\s*(?:and\s+)?|\s+and\s+', row['authors'])]}
            for row in rows]


def cikm_author_names(cell):
    from html.parser import HTMLParser

    class Names(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.depth = 0
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag == 'i':
                self.depth += 1

        def handle_endtag(self, tag):
            if tag == 'i':
                self.depth -= 1
                if self.depth < 0:
                    raise ValueError('Unbalanced CIKM affiliation')

        def handle_data(self, data):
            if self.depth == 0:
                self.parts.append(data)

    parser = Names()
    parser.feed(cell)
    parser.close()
    if parser.depth:
        raise ValueError('Truncated CIKM affiliation')
    names = [name.strip() for name in re.split(r',\s*(?:and\s+)?|\s+and\s+', ''.join(parser.parts))]
    if not names or not all(names):
        raise ValueError('Missing CIKM author')
    return names


def official_cikm2025(directory):
    text = (directory / 'cikm2025-accepted.html').read_text('utf8')
    if 'CIKM 2025' not in text or not re.search(r'id="t_01"[^>]*>Full Research Papers</div>', text):
        raise ValueError('CIKM 2025 Full Research Papers identity mismatch')
    section = re.search(r'<div id="ta2_01"[^>]*>.*?<table\b[^>]*>(.*?)</table>', text, re.S)
    if not section:
        raise ValueError('CIKM full-paper table missing')
    result, ids = [], set()
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', section[1], re.S):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)
        if not cells:
            continue
        if len(cells) != 3:
            raise ValueError('CIKM row has incorrect cell count')
        identity = plain(cells[0])
        # Six rows have blank submission IDs on the official page. Their
        # full-table membership plus exact title/authors/DOI are still checked.
        if identity:
            if not re.fullmatch(r'fp\d+', identity) or identity in ids:
                raise ValueError('CIKM wrong-track or duplicate submission ID')
            ids.add(identity)
        title = plain(cells[1])
        parse_issue = None
        try:
            names = cikm_author_names(cells[2])
        except ValueError as exc:
            # Retain this official row in the expected count, but never guess
            # authors from malformed markup or drop the whole source unit.
            names = []
            parse_issue = str(exc)
        if not title or (names and not all(names)):
            raise ValueError('CIKM title or authors missing')
        result.append({'title': title, 'authors': names, **({'parse_issue': parse_issue} if parse_issue else {})})
    if len(result) != 442:
        raise ValueError('CIKM 2025 full-paper count changed or truncated')
    return result


def official_wsdm2025(directory):
    text = (directory / 'wsdm2025-accepted.html').read_text('utf8')
    if 'WSDM 2025' not in text or 'Accepted Papers' not in text:
        raise ValueError('WSDM 2025 research-list identity mismatch')
    parts = re.findall(r'<p>\s*<strong>(.*?)</strong>\s*<em>(.*?)</em>\s*</p>', text, re.S)
    if len(parts) != 106:
        raise ValueError('WSDM 2025 research-list count changed or truncated')
    result = []
    for title, value in parts:
        depth, outside = 0, []
        for char in plain(value):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth < 0:
                    raise ValueError('Unbalanced WSDM author affiliation')
            elif depth == 0:
                outside.append(char)
        if depth:
            raise ValueError('Truncated WSDM author affiliation')
        names = [name.replace('*', '').strip() for name in ''.join(outside).split(';')]
        if not all(names):
            raise ValueError('Missing WSDM author')
        result.append({'title': plain(title), 'authors': names})
    if len({normalize_title(row['title']) for row in result}) != 106:
        raise ValueError('Duplicate WSDM title')
    return result


def official_sigir2025(directory):
    text = (directory / 'sigir2025-accepted.html').read_text('utf8')
    if 'SIGIR 2025' not in text:
        raise ValueError('SIGIR 2025 page identity mismatch')
    section = re.search(r'<h2[^>]*id="full-papers"[^>]*>.*?</h2>(.*?)(?=<h2)', text, re.S)
    if not section:
        raise ValueError('SIGIR 2025 full-paper section missing')
    parts = re.findall(r"<span class='accepted-paper-title'>(.*?)</span>\s*<span class='accepted-paper-author'>(.*?)</span>", section[1], re.S)
    if len(parts) != 239 or section[1].count("class='accepted-paper-title'") != 239:
        raise ValueError('SIGIR 2025 full-paper count changed or truncated')
    return [{'title': plain(title), 'authors': [plain(name) for name in authors.split(',')]}
            for title, authors in parts]


def official_sigir2023(directory):
    text = (directory / 'sigir2023-full.html').read_text('utf8')
    if ('SIGIR 2023' not in text and 'SIGIR | Taipei | Taiwan | 2023' not in text) or 'Full papers' not in text:
        raise ValueError('SIGIR 2023 full-paper page identity mismatch')
    # First establish each paragraph boundary; matching directly from <strong>
    # to <br> can consume the next paper when a title ends outside bold markup.
    paragraphs = re.findall(r'<p>(.*?)</p>', text, re.S)
    result = []
    for paragraph in paragraphs:
        if not re.match(r'\s*<strong>●', paragraph):
            continue
        pieces = re.split(r'<br\s*/?>', paragraph, maxsplit=1)
        if len(pieces) != 2:
            raise ValueError('SIGIR 2023 paper missing title/author boundary')
        title = plain(pieces[0]).removeprefix('●').strip()
        authors = [plain(name) for name in pieces[1].split(',')]
        if not title or not authors or not all(authors):
            raise ValueError('SIGIR 2023 missing title or author')
        result.append({'title': title, 'authors': authors})
    if len(result) != 165 or len({normalize_title(row['title']) for row in result}) != 165:
        raise ValueError('SIGIR 2023 full-paper count changed or truncated')
    return result


def official_wsdm2023(directory):
    text = (directory / 'wsdm2023-accepted.html').read_text('utf8')
    if ('WSDM 2023' not in text and "WSDM'23 - The 16th ACM International WSDM Conference" not in html.unescape(text)) or 'Accepted Papers' not in text:
        raise ValueError('WSDM 2023 accepted-list identity mismatch')
    parts = re.findall(r'<h4>(.*?)</h4>\s*<p>(.*?)</p>', text, re.S)
    if len(parts) != 123:
        raise ValueError('WSDM 2023 accepted-list count changed or truncated')
    result = []
    for title, authors in parts:
        depth, outside = 0, []
        for char in plain(authors):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth < 0:
                    raise ValueError('Unbalanced WSDM affiliation')
            elif depth == 0:
                outside.append(char)
        if depth:
            raise ValueError('Truncated WSDM affiliation')
        names = [name.replace('*', '').strip() for name in ''.join(outside).split(';')]
        if not all(names):
            raise ValueError('Missing WSDM author')
        result.append({'title': plain(title), 'authors': names})
    return result


def official_sigir2026(directory):
    """Read JSON literals embedded by Next.js, never execute the scripts."""
    text = (directory / 'sigir2026-home.html').read_text('utf8')
    if 'SIGIR 2026' not in text:
        raise ValueError('SIGIR 2026 page identity mismatch')
    blocks = set()
    for script in re.findall(r'<script[^>]*>(.*?)</script>', text, re.S):
        match = re.fullmatch(r'self\.__next_f\.push\((.*)\)', script)
        if not match:
            continue
        try:
            payload = json.loads(match[1])
        except ValueError:
            continue
        if (isinstance(payload, list) and len(payload) == 2 and isinstance(payload[1], str)
                and '<h2>Full Papers</h2>' in payload[1]):
            blocks.add(payload[1])
    if len(blocks) != 1:
        raise ValueError('Missing or conflicting SIGIR 2026 full-paper payload')
    section = re.search(r'<h2>Full Papers</h2>(.*?)(?=<h2>)', blocks.pop(), re.S)
    if not section:
        raise ValueError('Missing SIGIR full-paper section boundary')
    parts = re.findall(r'<p>\[fp\]\s*<i>(.*?)</i><br\s*/>\s*(.*?)</p>', section[1], re.S)
    if len(parts) != 233 or section[1].count('[fp]') != 233:
        raise ValueError('SIGIR 2026 full-paper count changed or truncated')
    return [{'title': plain(title), 'authors': [plain(name) for name in authors.split(',')]}
            for title, authors in parts]


def official_wsdm2026(directory):
    text = (directory / 'wsdm2026-accepted.html').read_text('utf8')
    if 'WSDM' not in text or '2026' not in text:
        raise ValueError('WSDM 2026 page identity mismatch')
    section = re.search(r'<h[1-6][^>]*>Full Papers</h[1-6]>(.*?)(?=<h[1-6][^>]*>Short Papers)', text, re.S)
    if not section:
        raise ValueError('WSDM 2026 full-paper boundaries missing')
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', section[1], re.S)
    if len(paragraphs) != 100:
        raise ValueError('WSDM 2026 full-paper count changed or truncated')
    result = []
    for paragraph in paragraphs:
        value = plain(paragraph)
        # A single-letter initial is not the author/title boundary. Require
        # the word immediately preceding the separator to contain >=2 letters.
        match = re.search(r'(?<=[^\W\d_][^\W\d_])\.\s+', value)
        if not match:
            raise ValueError('WSDM author/title separator missing')
        authors = [name.strip() for name in re.split(r',\s*(?:and\s+)?|\s+and\s+', value[:match.start()])]
        title = value[match.end():].strip()
        if not title or not all(authors):
            raise ValueError('WSDM title or authors missing')
        result.append({'title': title, 'authors': authors})
    return result


def official_www2026(directory):
    text = (directory / 'www2026-research.html').read_text('utf8')
    if 'The Web Conference 2026' not in text or 'Accepted Papers - Research Tracks' not in text:
        raise ValueError('WWW 2026 research-list identity mismatch')
    parts = re.findall(r'<li><span class="paper-id">\((rfp\d+)\)</span>(.*?)—\s*<span class="paper-authors">(.*?)</span></li>', text, re.S)
    if len(parts) != 676 or len({row[0] for row in parts}) != 676 or len(re.findall(r'rfp\d+', text)) != 676:
        raise ValueError('WWW 2026 research list truncated or duplicate IDs')
    result = []
    for identity, title, authors in parts:
        names = [name.strip() for name in re.split(r',\s*(?:and\s+)?|\s+and\s+', plain(authors))]
        if not plain(title) or not all(names):
            raise ValueError('WWW title or authors missing')
        result.append({'title': plain(title), 'authors': names, 'submission_id': identity})
    return result


SOURCES = {
    'WWW': ('https://www2024.thewebconf.org/accepted/research-tracks', official_www),
    'ACM MM': ('https://2024.acmmm.org/accepted-list', official_mm),
    'SIGIR': ('https://sigir-2024.github.io/infofiles/sigir2024-papers.updated.v3.jsonl', official_sigir),
    'WSDM': ('https://www.wsdm-conference.org/2024/accepted-papers/', official_wsdm),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--year', type=int, choices=[2023, 2024, 2025, 2026], default=2024)
    parser.add_argument('--venues', nargs='+', choices=sorted(set(SOURCES) | {'CIKM'}), help='Limit to selected verified track adapters')
    args = parser.parse_args()
    selected, units = {}, []
    evidence_files = {
        ('ACM MM', 2024): 'mm2024-accepted-chunk.txt',
        ('SIGIR', 2024): 'sigir2024-papers.jsonl',
        ('WSDM', 2024): 'wsdm2024-papers.html',
        ('WWW', 2024): 'www2024-research.html',
        ('WWW', 2023): 'www2023-research.csv',
        ('CIKM', 2025): 'cikm2025-accepted.html',
        ('WSDM', 2025): 'wsdm2025-accepted.html',
        ('SIGIR', 2025): 'sigir2025-accepted.html',
        ('SIGIR', 2023): 'sigir2023-full.html',
        ('SIGIR', 2026): 'sigir2026-home.html',
        ('WSDM', 2026): 'wsdm2026-accepted.html',
        ('WWW', 2026): 'www2026-research.html',
        ('WSDM', 2023): 'wsdm2023-accepted.html',
    }
    sources = {
        2024: SOURCES,
        2023: {'WSDM': ('https://www.wsdm-conference.org/2023/program/accepted-papers', official_wsdm2023),
               'SIGIR': ('https://sigir.org/sigir2023/program/accepted-papers/full-papers/', official_sigir2023),
               'WWW': ('https://archives.iw3c2.org/www2023/accepted/accepted_papers.csv', official_www2023)},
        2025: {'SIGIR': ('https://sigir2025.dei.unipd.it/accepted-papers.html', official_sigir2025),
               'CIKM': ('https://cikm2025.org/program/accepted-papers', official_cikm2025),
               'WSDM': ('https://www.wsdm-conference.org/2025/accepted-papers/', official_wsdm2025)},
        2026: {'WWW': ('https://www2026.thewebconf.org/accepted/research-tracks.html', official_www2026),
               'WSDM': ('https://wsdm-conference.org/2026/index.php/accepted-papers/', official_wsdm2026),
               'SIGIR': ('https://sigir2026.org/en-AU', official_sigir2026)},
    }[args.year]
    if args.venues and any(venue not in sources for venue in args.venues):
        parser.error('No verified track adapter for the selected venue/year')
    for venue, (url, parse) in sources.items():
        if args.venues and venue not in args.venues:
            continue
        inventory = json.loads((args.evidence / f"inventory-{venue.replace(' ', '_')}-{args.year}.json").read_text('utf8'))
        records, issues = match_official_track(inventory, parse(args.evidence))
        selected[venue] = records
        units.append({'venue': venue, 'year': args.year, 'official_source': url,
                      'official_research_count': len(records) + len(issues),
                      'evidence_file': evidence_files[(venue, args.year)],
                      'evidence_sha256': hashlib.sha256((args.evidence / evidence_files[(venue, args.year)]).read_bytes()).hexdigest(),
                      'matched_count': len(records), 'unresolved': issues,
                      'full_venue_coverage_verified': False})
    report = {'database_modified': False, 'units': units, 'full_collection_verified': False}
    if args.apply:
        path = args.database.resolve()
        if not path.is_file():
            raise ValueError('Existing database required')
        report['backup'] = str(_backup(path))
        engine = _make_engine('sqlite:///' + path.as_posix())
        try:
            with Session(engine) as session:
                rules, thresholds = load_rules(session), load_thresholds(session)
                for unit in units:
                    venue = session.query(Venue).filter(Venue.abbr == unit['venue'], Venue.type == 'conf', Venue.active == 1).one()
                    result = apply_records(session, selected[venue.abbr], venue)
                    for raw in selected[venue.abbr]:
                        paper = session.query(Paper).filter(Paper.doi == raw.doi, Paper.venue_id == venue.id, Paper.year == args.year).one_or_none()
                        if paper is None or paper.title_norm != normalize_title(raw.title):
                            continue
                        evidence = 'Official research-track list: ' + unit['official_source']
                        if evidence not in (paper.note or ''):
                            paper.note = (paper.note or '') + '\n' + evidence
                        apply_tagging(session, paper.id, paper.title, paper.abstract, rules, thresholds)
                    session.commit()
                    unit['import'] = result
                report['database_modified'] = True
        finally:
            engine.dispose()
    target = args.evidence / ('official-track-import.json' if args.apply else 'official-track-audit.json')
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    history = target.with_name(target.stem + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    history.write_text(payload, encoding='utf8')
    target.write_text(payload, encoding='utf8')
    print(json.dumps({'report': str(target), 'database_modified': report['database_modified'], 'units': [{k:v for k,v in u.items() if k!='unresolved'} for u in units]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
