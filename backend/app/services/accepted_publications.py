"""Verified acceptance references, explicitly separate from published papers."""

import json
import re

from app.api.filtering import PaperFilters, paper_query
from app.api.serializers import safe_http_url
from app.cleaning import normalize_title
from app.config import settings
from app.models import Paper, Venue

REFERENCE_ROWS = json.loads((settings.seeds_dir / 'accepted_publications.json').read_text('utf8'))['papers']
REFERENCE_KEYS = {'reference_id', 'title', 'authors', 'venue', 'year', 'level', 'status', 'official_url',
                  'preprint_url', 'aliases', 'directions', 'evidence_sha256', 'verified_on'}


def validate_accepted_references(rows, venues):
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError('Invalid acceptance reference list')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != REFERENCE_KEYS:
            raise ValueError('Invalid acceptance reference fields')
        venue = venues.get(row['venue'])
        if (not venue or venue['type'] != 'conf' or venue['level'] != row['level']
                or row['level'] not in {'A', 'B'} or row['status'] != 'accepted_publication_unverified'
                or not isinstance(row['reference_id'], str) or not re.fullmatch(r'[a-z0-9-]{8,80}', row['reference_id'])
                or row['reference_id'] in seen or type(row['year']) is not int or not 2023 <= row['year'] <= 2100
                or not isinstance(row['title'], str) or not 1 <= len(row['title']) <= 2000
                or not isinstance(row['authors'], list) or not row['authors']
                or not all(isinstance(a, str) and 0 < len(a) <= 200 for a in row['authors'])
                or not isinstance(row['aliases'], list) or not all(isinstance(a, str) and 0 < len(a) <= 2000 for a in row['aliases'])
                or not isinstance(row['directions'], list) or not all(isinstance(d, str) and re.fullmatch('[a-z]+', d) for d in row['directions'])
                or not row['official_url'] or safe_http_url(row['official_url']) != row['official_url']
                or not re.fullmatch('[a-f0-9]{64}', row['evidence_sha256'])
                or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', row['verified_on'])
                or (row['preprint_url'] is not None and not re.fullmatch(r'https://arxiv\.org/abs/\d{4}\.\d{4,5}', row['preprint_url']))):
            raise ValueError('Unverified acceptance reference')
        seen.add(row['reference_id'])


def accepted_references(db, candidates=None):
    candidates = REFERENCE_ROWS if candidates is None else candidates
    if not candidates:
        return []
    names = {r['venue'] for r in candidates}
    sources = {v.abbr: {'type': v.type, 'level': v.ccf_level}
               for v in db.query(Venue.abbr, Venue.type, Venue.ccf_level)
               .filter(Venue.ccf_level.in_(('A', 'B')), Venue.abbr.in_(names))}
    rows = [r for r in candidates if r['venue'] in sources]
    validate_accepted_references(rows, sources)
    if not rows:
        return []
    published = set(paper_query(db, PaperFilters()).filter(
        Paper.title_norm.in_([normalize_title(r['title']) for r in rows])
    ).with_entities(Paper.title_norm, Venue.abbr, Paper.year).all())
    return [r for r in rows if (normalize_title(r['title']), r['venue'], r['year']) not in published]


def match_accepted_references(rows, q, filters, mode='auto', topic=None):
    query = normalize_title(q)
    if not query and not topic and (str(q or '').strip() or not filters.venue):
        return []
    matched = []
    for row in rows:
        if (filters.pdf_status or (filters.level and filters.level != row['level'])
                or (filters.type and filters.type != 'conf')
                or (filters.venue and filters.venue != row['venue'])
                or (filters.year and filters.year != row['year'])
                or (filters.directions and not set(filters.directions) & set(row['directions']))
                or (topic and topic not in row['directions'])
                or (filters.access and (bool(row['preprint_url']) != (filters.access == 'oa')))):
            continue
        values = [normalize_title(row['title']), *map(normalize_title, row['aliases'])]
        if topic or not query or (query == values[0] if mode == 'exact' else all(word in ' '.join(values) for word in query.split())):
            matched.append(dict(row))
    return matched


def attach_accepted_references(db, result, q, filters, mode='auto'):
    candidates = match_accepted_references(REFERENCE_ROWS, q, filters, mode,
                                          (result.get('query_topic') or {}).get('code'))
    rows = accepted_references(db, candidates)
    return {**result, 'accepted_items': rows} if rows else result
