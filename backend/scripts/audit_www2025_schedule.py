"""Read-only exact-title comparison of the official archived WWW 2025 schedule.

This is not an admission command: the schedule omits authors and may omit
poster-only papers. Main-proceedings metadata does not alone certify a track.
"""
import argparse
import hashlib
import html
import json
import re
from collections import defaultdict
from pathlib import Path

from app.cleaning import normalize_title
from app.collectors.crossref import metadata_text
from app.collectors.acm_proceedings import validate_article
from scripts.import_acm_research_tracks import plain


def parse_schedule(page, *, expected_sessions=32):
    frames = [html.unescape(value) for value in re.findall(r'srcDoc="(.*?)"', page, re.S)]
    rows, sessions = [], set()
    for frame in frames:
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', frame, re.S):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
            labels = [plain(cell) for cell in cells]
            selected = [label for label in labels if re.match(r'Session\s*\d+\b', label)]
            if not selected:
                continue
            if len(selected) != 1:
                raise ValueError('Ambiguous research session label')
            session = selected[0]
            if session in sessions:
                raise ValueError('Duplicate research session')
            sessions.add(session)
            for line in re.split(r'<br\s*/?>', cells[-1]):
                value = plain(line)
                match = re.fullmatch(r'(\d+),\s*(.+)', value)
                if not match:
                    # Explicit journal presentations are not conference papers.
                    if re.match(r'TWeb\d+,', value):
                        continue
                    if value and not value.startswith('Topic:'):
                        raise ValueError('Unparsed research schedule line: ' + value[:100])
                    continue
                rows.append({'submission_id': match[1], 'title': match[2], 'session': session})
    if len(sessions) != expected_sessions or not rows:
        raise ValueError('Research schedule session count mismatch')
    return rows


def parse_posters(page, *, expected_count=408):
    """Official Research-N numbering proves this list's extent, not author identity."""
    result, allocated = [], set()
    for frame in re.findall(r'srcDoc="(.*?)"', page, re.S):
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html.unescape(frame), re.S):
            cells = [plain(cell) for cell in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
            matches = [(i, re.fullmatch(r'Research-(\d+)', cell)) for i, cell in enumerate(cells)]
            matches = [(i, match) for i, match in matches if match]
            if not matches:
                continue
            if len(matches) != 1:
                raise ValueError('Ambiguous research poster row')
            i, match = matches[0]
            number = int(match[1])
            if number in allocated or len(cells[i + 1:]) != 2 or not cells[i + 1].isdigit() or not cells[i + 2]:
                raise ValueError('Duplicate or malformed research poster')
            allocated.add(number)
            result.append({'poster_number': number, 'submission_id': cells[i + 1], 'title': cells[i + 2]})
    if allocated != set(range(1, expected_count + 1)):
        raise ValueError('Incomplete research poster numbering')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    path = args.evidence / 'www2025-schedule.html'
    scheduled = parse_schedule(path.read_text('utf8'))
    inventory = json.loads((args.evidence / 'inventory-WWW-2025.json').read_text('utf8'))
    titles = defaultdict(list)
    for item in inventory['items']:
        validate_article(item, inventory['parent'], inventory['container'], 2025)
        titles[normalize_title(metadata_text(item['title'][0]))].append(item)
    matched, unresolved = [], []
    counts = defaultdict(int)
    for row in scheduled:
        counts[row['submission_id']] += 1
    for row in scheduled:
        if counts[row['submission_id']] != 1:
            unresolved.append({**row, 'reason': 'duplicate_official_submission_id'})
            continue
        hits = titles.get(normalize_title(row['title']), [])
        if len(hits) == 1:
            matched.append({**row, 'doi': hits[0]['DOI'], 'publisher_authors': hits[0].get('author', []),
                            'official_author_comparison': 'not_available'})
        else:
            unresolved.append({**row, 'reason': 'title_missing_or_ambiguous', 'matches': len(hits)})
    report = {'read_only': True, 'database_modified': False,
              'official_url': 'https://archives.iw3c2.org/www2025/full-schedule',
              'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'official_research_sessions': 32, 'scheduled_titles': len(scheduled),
              'exact_title_matches': len(matched), 'matched': matched, 'unresolved': unresolved,
              'publisher_inventory_count': len(inventory['items']),
              'full_coverage_verified': False, 'admitted': 0,
              'remaining_evidence': 'Schedule does not provide authors; collect official research list or independent identity evidence. Poster-only completeness unverified.'}
    poster_path = args.evidence / 'www2025-posters.html'
    if poster_path.is_file():
        posters = parse_posters(poster_path.read_text('utf8'))
        poster_matches, poster_issues = [], []
        id_counts = defaultdict(int)
        for row in posters:
            id_counts[row['submission_id']] += 1
        for row in posters:
            hits = titles.get(normalize_title(row['title']), [])
            if id_counts[row['submission_id']] == 1 and len(hits) == 1:
                poster_matches.append({**row, 'doi': hits[0]['DOI'], 'official_author_comparison': 'not_available'})
            else:
                poster_issues.append({**row, 'reason': 'duplicate_submission_id' if id_counts[row['submission_id']] != 1 else 'title_missing_or_ambiguous'})
        report['research_posters'] = {'official_count': len(posters), 'exact_title_matches': len(poster_matches),
            'source': 'https://archives.iw3c2.org/www2025/poster-session',
            'sha256': hashlib.sha256(poster_path.read_bytes()).hexdigest(),
            'matched': poster_matches, 'unresolved': poster_issues}
        report['remaining_evidence'] = '408 consecutively numbered research posters recovered; author identities and correspondence with all formally published papers remain unverified. No automatic admission.'
    target = args.evidence / 'www2025-schedule-audit.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('matched', 'unresolved', 'research_posters')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
