"""ACM publisher-deposited DOI inventory, NOT a main/full-paper track certificate.

Only exact containers with independently resolved parent proceedings are accepted.
No database writes, private-key access, publisher challenges or PDF requests.
"""
import asyncio
import re

import httpx

from app.cleaning import normalize_doi
from app.collectors.crossref import publication_date

API = 'https://api.crossref.org/works'


def validate_parent(parent, title, year):
    doi = normalize_doi(parent.get('DOI')) or ''
    if not re.fullmatch(r'10\.1145/\d+', doi):
        raise ValueError('Parent is not an ACM proceedings DOI')
    if parent.get('type') != 'proceedings' or parent.get('title') != [title]:
        raise ValueError('Parent proceedings title/type mismatch')
    if publication_date(parent)[0] != year:
        raise ValueError('Parent proceedings year mismatch')
    if any(word in title.casefold() for word in ('companion', 'workshop', 'adjunct')):
        raise ValueError('Companion/workshop containers require separate scope review')
    return doi


def validate_article(item, parent, title, year):
    parent_doi = validate_parent(parent, title, year)
    doi = normalize_doi(item.get('DOI')) or ''
    if not re.fullmatch(re.escape(parent_doi) + r'\.\d+', doi):
        raise ValueError('Article DOI does not belong to verified proceedings')
    if item.get('type') != 'proceedings-article' or item.get('container-title') != [title]:
        raise ValueError('Article container/type mismatch')
    if publication_date(item)[0] != year:
        raise ValueError('Article publication year mismatch')
    if not item.get('title') or not isinstance(item['title'][0], str) or not item['title'][0].strip():
        raise ValueError('Article title missing')
    # Missing authors may indicate front matter; never silently admit it.
    if not item.get('author'):
        raise ValueError('Article authors missing; requires review')
    return True


async def _get(client, url, *, delay, params=None):
    for attempt in range(3):
        await asyncio.sleep(delay if attempt == 0 else max(delay, 15 * attempt))
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError:
            if attempt == 2:
                raise
            continue
        if response.status_code in (429, 502, 503, 504) and attempt < 2:
            retry = response.headers.get('Retry-After', '')
            if retry.isdigit():
                await asyncio.sleep(min(int(retry), 120))
            continue
        response.raise_for_status()
        return response.json()['message']
    raise ValueError('Crossref request exhausted retries')


async def fetch_inventory(client, title, year, parent_doi, *, delay=3, on_page=None, other_parent_dois=()):
    if not isinstance(title, str) or ',' in title or not 2000 <= year <= 2100:
        raise ValueError('Invalid exact container filter')
    if not re.fullmatch(r'10\.1145/\d+', parent_doi):
        raise ValueError('Invalid parent DOI')
    parent = await _get(client, API + '/' + parent_doi, delay=delay)
    if validate_parent(parent, title, year) != parent_doi:
        raise ValueError('Resolved parent identity differs')
    others = tuple(other_parent_dois)
    if len(others) > 8 or len(set(others)) != len(others) or parent_doi in others:
        raise ValueError('Invalid alternate parent set')
    partitions = {}
    for other in others:
        if not re.fullmatch(r'10\.1145/\d+', other):
            raise ValueError('Invalid alternate parent DOI')
        metadata = await _get(client, API + '/' + other, delay=delay)
        if validate_parent(metadata, title, year) != other:
            raise ValueError('Alternate parent response mismatch')
        partitions[other] = {'parent': metadata, 'items': [], 'rejected': []}
    items, rejected, seen = [], [], set()
    cursor = '*'
    advertised = None
    for page in range(100):
        message = await _get(client, API, delay=delay, params={
            'filter': f'type:proceedings-article,container-title:{title},from-pub-date:{year}-01-01,until-pub-date:{year}-12-31',
            'rows': 1000, 'cursor': cursor,
        })
        total = message.get('total-results')
        if type(total) is not int or total <= 0 or not isinstance(message.get('items'), list):
            raise ValueError('Invalid or empty Crossref inventory')
        if advertised is not None and total != advertised:
            raise ValueError('Inventory changed while paginating; retry from a fresh snapshot')
        advertised = total
        rows = message['items']
        if not rows:
            raise ValueError('Inventory ended before advertised count')
        for item in rows:
            doi = normalize_doi(item.get('DOI'))
            if not doi or doi in seen:
                raise ValueError('Inventory contains missing or duplicate DOI')
            seen.add(doi)
            article_parent = doi.rsplit('.', 1)[0]
            if article_parent == parent_doi:
                metadata, accepted_rows, rejected_rows = parent, items, rejected
            elif article_parent in partitions:
                partition = partitions[article_parent]
                metadata, accepted_rows, rejected_rows = partition['parent'], partition['items'], partition['rejected']
            else:
                raise ValueError('Article DOI does not belong to verified proceedings')
            # Fail the unit on identity mismatch. Quarantine authorless front
            # matter separately so it cannot break otherwise valid metadata.
            if not item.get('author'):
                validate_article({**item, 'author': [{'name': 'validation-only'}]}, metadata, title, year)
                rejected_rows.append({'doi': doi, 'reason': 'missing_authors', 'item': item})
            else:
                validate_article(item, metadata, title, year)
                accepted_rows.append(item)
        if on_page:
            on_page(page + 1, rows, len(seen), advertised)
        if len(seen) == advertised:
            return {'parent': parent, 'container': title, 'year': year, 'items': items,
                    'rejected': rejected, 'advertised': advertised,
                    'container_count': len(seen), 'selected_parent_count': len(items) + len(rejected),
                    'other_parent_partitions': partitions,
                    'doi_inventory_complete': True, 'track_status': 'unverified',
                    'full_track_coverage_verified': False}
        if len(seen) > advertised or not message.get('next-cursor'):
            raise ValueError('Inventory count/cursor mismatch')
        cursor = message['next-cursor']
    raise ValueError('Inventory pagination limit exceeded')


def canonical_authors(authors):
    """Collapse only exact repeated objects carrying the same explicit ORCID.

    Same names with different/missing ORCIDs remain separate. The raw inventory
    is immutable and the number of collapsed publisher entries is recorded.
    """
    import json
    result, seen = [], set()
    removed = 0
    for author in authors:
        orcid = author.get('ORCID', '')
        key = json.dumps(author, sort_keys=True, ensure_ascii=False)
        valid = bool(re.fullmatch(r'https?://orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]', orcid))
        if valid and key in seen:
            removed += 1
            continue
        result.append(author)
        if valid:
            seen.add(key)
    return result, removed


def match_official_track(inventory, official):
    """Join an explicitly selected official research list to publisher identities.

    No fuzzy title/author matching. Unresolved spelling differences stay in the
    report for source review rather than admitting a guessed publication.
    """
    from collections import Counter, defaultdict
    from app.services.publication_identity import _tokens
    from app.cleaning import author_name_norm, clean_author_name, normalize_title
    from app.collectors.crossref import item_to_raw, metadata_text

    index = defaultdict(list)
    for item in inventory['items']:
        validate_article(item, inventory['parent'], inventory['container'], inventory['year'])
        index[normalize_title(metadata_text(item['title'][0]))].append(item)
    seen = set()
    records, issues = [], []
    for entry in official:
        title = normalize_title(entry['title'])
        if title in seen:
            raise ValueError('Duplicate official track title; resolve before import')
        seen.add(title)
        if entry.get('parse_issue'):
            issues.append({'title': entry['title'], 'reason': 'official_author_markup_invalid', 'detail': entry['parse_issue']})
            continue
        hits = index.get(title, [])
        if len(hits) != 1:
            issues.append({'title': entry['title'], 'reason': 'title_missing_or_ambiguous'})
            continue
        item = hits[0]
        authors, duplicate_entries = canonical_authors(item.get('author') or [])
        raw = item_to_raw({**item, 'author': authors})
        expected = {author_name_norm(clean_author_name(name)) for name in entry['authors']}
        actual = {author_name_norm(name) for name in raw.authors} if raw else set()
        # Exact full-name token multisets permit family/given reordering only.
        # Counts and every name token must agree; no initials/aliases are guessed.
        official_names = [tuple(sorted(_tokens(name))) for name in entry['authors']]
        publisher_names = [tuple(sorted(_tokens(name))) for name in raw.authors] if raw else []
        full_token_match = (bool(official_names) and all(official_names)
                            and Counter(official_names) == Counter(publisher_names))
        # Sets alone can hide a second person with the same name. Preserve
        # author multiplicity unless exact ORCID-bearing duplicates were proven.
        if (not expected or '' in expected or len(entry['authors']) != len(raw.authors)
                or (expected != actual and not full_token_match)):
            issues.append({'title': entry['title'], 'reason': 'author_mismatch',
                           'official_only': sorted(expected - actual), 'publisher_only': sorted(actual - expected)})
            continue
        raw.extra.update(publisher_key=raw.official_url, verified_track='official_research_list',
                         abstract=metadata_text(item.get('abstract', '')) or None,
                         duplicate_author_entries_collapsed=duplicate_entries)
        records.append(raw)
    return records, issues
