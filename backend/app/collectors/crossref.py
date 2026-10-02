"""Publisher-deposited Crossref metadata; DOI + container identity are both required.

Crossref inventories are a supplementary source, not a promise that every
accepted paper has a registered DOI. No full text/PDF requests are made.
"""
import asyncio
import html
import re
from datetime import date

import httpx

from app.cleaning import clean_author_name, clean_title, normalize_doi, normalize_title
from app.collectors.dblp import RawPaper
from app.ratelimit import AsyncTokenBucket

API = "https://api.crossref.org"
SELECT = "DOI,title,author,type,published,published-print,published-online,event,container-title,volume,issue,ISSN"
PREFIXES = ("10.1609", "10.18653", "10.24963", "10.3233")
RETRYABLE_STATUS = {429, 502, 503, 504}


async def request_with_retry(client, url, *, params=None, attempts=5):
    """Make a polite Crossref request with bounded retry-after handling."""
    if attempts < 1:
        raise ValueError("At least one Crossref request attempt is required")
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(min(60.0, 5.0 * (attempt + 1)))
            continue
        if response.status_code not in RETRYABLE_STATUS or attempt == attempts - 1:
            return response
        retry_after = response.headers.get("retry-after", "")
        try:
            delay = min(120.0, max(1.0, float(retry_after)))
        except ValueError:
            delay = min(60.0, 5.0 * (attempt + 1))
        await asyncio.sleep(delay)
    raise RuntimeError("Crossref retry loop ended unexpectedly")

# Exact publisher-deposited main-proceedings titles, not a fuzzy title query.
ECML_BASE = "Machine Learning and Knowledge Discovery in Databases"
ECML_CONTAINERS = (ECML_BASE, *(ECML_BASE + suffix for suffix in (
    ": Research Track", ". Research Track", ". Applied Data Science Track",
    ": Applied Data Science and Demo Track", ". Research Track and Demo Track",
    ". Research Track and Applied Data Science Track",
    ". Applied Data Science Track and Demo Track",
    ". Applied Data Science Track, Demo Track and Industrial Track",
)))


def ecml_conference_year(item):
    """Require the actual parent book to prove conference identity AND year.

    A 2023 imprint can be ECML PKDD 2022; a 2026 imprint can be 2025.
    The chapter DOI, parent DOI, title, and explicit proceedings subtitle
    must all agree. Print dates alone never establish an ECML conference year.
    """
    parent = item.get("_ecml_parent") or {}
    doi = normalize_doi(item.get("DOI")) or ""
    parent_doi = normalize_doi(parent.get("DOI")) or ""
    if not re.fullmatch(r"10\.1007/978-[\d-]+_\d+", doi) or doi.rsplit("_", 1)[0] != parent_doi:
        return None
    titles = parent.get("title") or []
    if parent.get("type") != "book" or len(titles) != 1 or titles[0] not in ECML_CONTAINERS:
        return None
    if titles[0] not in (item.get("container-title") or []) or item.get("type") != "book-chapter":
        return None
    subtitle = " ".join(parent.get("subtitle") or [])
    if any(word in subtitle.lower() for word in ("workshop", "tutorial", "doctoral")):
        return None
    years = set(re.findall(r"European Conference, ECML PKDD (20\d{2})\b", subtitle))
    if len(years) != 1 or "Proceedings" not in subtitle:
        return None
    return int(years.pop())




# Exact registry variants verified 2026-10-01; evidence is recorded in
# seeds/journal_identity_provenance.json. Do not generalize to fuzzy aliases.
JOURNAL_NAME_VARIANTS = {
    'JSA': ('1383-7621', 'Journal of Systems Architecture: Embedded Software Design', 'Journal of Systems Architecture'),
    'Performance Evaluation: An International Journal': ('0166-5316', 'Performance Evaluation: An International Journal', 'Performance Evaluation'),
    'SoSyM': ('1619-1366', 'Software and Systems Modeling', 'Software & Systems Modeling'),
    'IPM': ('0306-4573', 'Information Processing and Management', 'Information Processing & Management'),
    'CSCW Journal': ('0925-9724', 'Computer Supported Cooperative Work', 'Computer Supported Cooperative Work (CSCW)'),
}


def journal_identities(venue):
    """ISSN/name pairs, including the verified 2025 TASLP continuation.

    Do not alter user venue settings or match a different journal on acronym.
    """
    pairs = {(venue.issn, normalize_title(venue.name).removeprefix('the '))} if venue.issn else set()
    variant = JOURNAL_NAME_VARIANTS.get(getattr(venue, 'abbr', None))
    if (variant and venue.issn == variant[0]
            and normalize_title(venue.name) == normalize_title(variant[1])):
        pairs.add((variant[0], normalize_title(variant[2]).removeprefix('the ')))
    if (getattr(venue, 'abbr', None) == 'TASLP' and venue.issn in {'2329-9290', '2329-9304', '2998-4173'}
            and normalize_title(venue.name) in {
                'ieee/acm transactions on audio speech and language processing',
                'ieee acm transactions on audio speech and language processing',
                'ieee transactions on audio speech and language processing'}):
        pairs.update({('2329-9290', 'ieee acm transactions on audio speech and language processing'),
                      ('2329-9304', 'ieee acm transactions on audio speech and language processing'),
                      ('2998-4173', 'ieee transactions on audio speech and language processing')})
    from app.collectors.journal_serials import serial_sources
    pairs.update((record['issn'], normalize_title(record['title']).removeprefix('the '))
                 for record in serial_sources(venue))
    return pairs

def publication_date(item: dict) -> tuple[int, str | None]:
    # For journals, the issue/print year takes precedence over early access.
    fields = ("published-print", "published", "published-online")
    for field in fields:
        parts = (item.get(field) or {}).get("date-parts") or []
        if not parts or not parts[0] or type(parts[0][0]) is not int:
            continue
        year = parts[0][0]
        if not 2000 <= year <= 2100:
            continue
        full = None
        if len(parts[0]) == 3:
            try:
                full = date(*parts[0]).isoformat()
            except (ValueError, TypeError):
                pass
        return year, full
    return 0, None


def metadata_text(value: str) -> str:
    # Strip only known publisher markup. Literal model tokens such as <SEG>,
    # <safe> and <SYNTACT> are scientific title content, not HTML to discard.
    value = html.unescape(value or "")
    value = re.sub(r'<(?:jats:)?(?:inline-graphic|alt-text|long-desc)\b[^>]*>.*?</(?:jats:)?(?:inline-graphic|alt-text|long-desc)>', '', value, flags=re.IGNORECASE | re.DOTALL)
    tags = (r"(?:jats|mml):[a-z][\w.-]*|italic|bold|sub|sup|i|b|em|strong|scp|u|tt|underline|"
            r"inline-formula|tex-math|math|mi|mn|mo|mrow|msub|msup|msubsup|mfrac|msqrt|mtext")
    value = re.sub(r"</?(?:" + tags + r")(?:\s[^<>]*?)?\s*/?>", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def identify_venue(item: dict, venues: dict):
    doi = normalize_doi(item.get("DOI")) or ""
    container = normalize_title(metadata_text(" ".join(item.get("container-title") or [])))
    if item.get("type") == "journal-article":
        issns = set(item.get("ISSN") or [])
        for venue in venues.values():
            if venue.type == "journal" and any(issn in issns and container.removeprefix("the ") == name for issn, name in journal_identities(venue)):
                return venue
    from app.collectors.catalog_conferences import identify_catalog_conference
    # These adapters enforce publisher namespaces, parent-book identities or
    # track-specific DOI rules. Generic title matching must never override them.
    specialized = {'AAAI', 'ICAPS', 'IJCAI', 'KR', 'ACL', 'EMNLP', 'COLING', 'ECAI', 'ECML-PKDD', 'ICRA'}
    catalog_match = identify_catalog_conference(item, {
        name: venue for name, venue in venues.items()
        if name not in specialized and getattr(venue, 'abbr', None) not in specialized
    })
    if catalog_match:
        return catalog_match
    abbr = "ECML-PKDD" if ecml_conference_year(item) else None
    if re.fullmatch(r'20\d{2} ieee international conference on robotics and automation icra', container) and re.match(r'10\.1109/icra\d+\.20\d{2}\.', doi):
        abbr = 'ICRA'
    if doi.startswith("10.3233/faia") and any(re.fullmatch(r"ecai 20\d{2}", normalize_title(c)) for c in (item.get("container-title") or [])):
        abbr = "ECAI"
    if doi.startswith("10.1609/aaai.") and container == "proceedings of the aaai conference on artificial intelligence":
        abbr = "AAAI"
    elif doi.startswith("10.1609/icaps.") and "international conference on automated planning and scheduling" in container:
        abbr = "ICAPS"
    elif re.match(r"10\.24963/ijcai\.20\d{2}/", doi) and "joint conference on artificial intelligence" in container:
        abbr = "IJCAI"
    elif re.match(r"10\.24963/kr\.20\d{2}/", doi) and "knowledge representation and reasoning" in container:
        abbr = "KR"
    elif re.match(r"10\.18653/v1/20\d{2}\.acl-(?:long|main)\.", doi) and "annual meeting of the association for computational linguistics" in container:
        abbr = "ACL"
    elif re.match(r"10\.18653/v1/20\d{2}\.emnlp-main\.", doi) and "empirical methods in natural language processing" in container:
        abbr = "EMNLP"
    elif re.match(r"10\.18653/v1/20\d{2}\.coling-main\.", doi) and "international conference on computational linguistics" in container:
        abbr = "COLING"
    # Findings/workshop metadata is not evidence for the main CCF proceedings.
    if any(word in container for word in ("findings of", "workshop", "tutorial", "symposium")):
        return None
    return venues.get(abbr)


def item_to_raw(item: dict) -> RawPaper | None:
    doi = normalize_doi(item.get("DOI"))
    titles = item.get("title") or []
    year, published = publication_date(item)
    conference_year = ecml_conference_year(item)
    if conference_year:
        year = conference_year
        published = published if published and published.startswith(f"{year}-") else None
    if not doi or not titles or not year or item.get("type") not in ("proceedings-article", "journal-article", "book-chapter"):
        return None
    return RawPaper(
        # The existing schema uses 'manual' for DOI-identified imports.
        # Provenance is explicit in extra/note; never forge a DBLP/OpenAlex ID.
        source="manual", venue_key=doi, doi=doi, title=clean_title(metadata_text(titles[0])), year=year,
        publication_date=published, official_url="https://doi.org/" + doi,
        authors=[clean_author_name(" ".join(filter(None, (a.get("given"), a.get("family"))))) for a in item.get("author", [])],
        extra={"provenance": "crossref_publisher"},
    )


async def fetch_prefix(client, prefix, year_from, year_to, *, on_page=None, max_pages=200):
    if prefix not in PREFIXES:
        raise ValueError("Only configured publisher prefixes are permitted")
    return await _fetch_inventory(client, f"{API}/prefixes/{prefix}/works", prefix, year_from, year_to, on_page=on_page, max_pages=max_pages)


async def fetch_journal(client, issn, year_from, year_to, *, on_page=None, max_pages=200):
    if not re.fullmatch(r"\d{4}-\d{3}[\dX]", issn):
        raise ValueError("Invalid ISSN")
    # Crossref's generic publication-date filter may use the earlier online
    # date. Union it with issue/print dates so an older prepublication is not
    # omitted from a requested final publication year. Deduplicate by real DOI.
    result, seen = [], set()
    for field in ("pub-date", "print-pub-date"):
        def accept_page(label, page, count, total, records, *, field=field):
            fresh = []
            for item in records:
                doi = normalize_doi(item.get("DOI"))
                if doi not in seen:
                    seen.add(doi)
                    fresh.append(item)
            result.extend(fresh)
            if on_page and fresh:
                on_page(label + ":" + field, page, count, total, fresh)
        await _fetch_inventory(client, f"{API}/journals/{issn}/works", issn,
                               year_from, year_to, on_page=accept_page,
                               max_pages=max_pages, date_field=field)
    return result



async def fetch_container(client, title, year_from, year_to, *, on_page=None, max_pages=200):
    if title not in ECML_CONTAINERS and not re.fullmatch(r'20\d{2} IEEE International Conference on Robotics and Automation \(ICRA\)', title):
        raise ValueError('Only verified main-conference container titles are permitted')
    if title == ECML_BASE + '. Applied Data Science Track, Demo Track and Industrial Track':
        # Crossref uses commas to delimit filters; a literal comma in this
        # container is not representable there. This is the publisher-verified
        # 2026 Part X eISBN (parent DOI 10.1007/978-3-032-37685-5).
        # Parent-book validation below still checks the actual conference year.
        extra_filter = 'isbn:9783032376855'
    else:
        extra_filter = 'container-title:' + title
    return await _fetch_inventory(client, f'{API}/works', title, year_from, year_to, on_page=on_page, max_pages=max_pages, extra_filter=extra_filter)

async def _fetch_inventory(client, endpoint, label, year_from, year_to, *, on_page=None, max_pages=200, extra_filter="", date_field="pub-date", query=None):
    if date_field not in {"pub-date", "print-pub-date"}:
        raise ValueError("Unsupported publication date filter")
    cursor = "*"
    seen = set()
    limiter = AsyncTokenBucket(1)
    result = []
    advertised = None
    for page in range(max_pages):
        await limiter.acquire()
        response = await request_with_retry(client, endpoint, params={
            "filter": f"from-{date_field}:{year_from}-01-01,until-{date_field}:{year_to}-12-31" + ("," + extra_filter if extra_filter else ""),
            "rows": 1000, "cursor": cursor, "select": SELECT, **({"sort": "score", **query} if query else {}),
        })
        response.raise_for_status()
        message = response.json().get("message")
        if not isinstance(message, dict) or not isinstance(message.get("items"), list):
            raise ValueError("Invalid Crossref page")  # noqa: TRY004 - malformed remote data, not a caller type error
        if advertised is None:
            advertised = int(message["total-results"])
        items = message["items"]
        if not items:
            if len(seen) < advertised:
                raise ValueError("Crossref ended before its advertised inventory size")
            return result
        ids = [normalize_doi(item.get("DOI")) for item in items]
        if not all(ids) or any(doi in seen for doi in ids) or len(set(ids)) != len(ids):
            raise ValueError("Crossref inventory repeated or omitted an identifier")
        seen.update(ids)
        result.extend(items)
        if on_page:
            on_page(label, page + 1, len(seen), advertised, items)
        if len(seen) >= advertised:
            return result
        cursor = message.get("next-cursor")
        if not cursor:
            raise ValueError("Crossref inventory has no continuation cursor")
        # Crossref scroll cursors may remain identical between distinct pages.
        # Verify page identities instead of requiring a changed cursor string.
    raise ValueError("Crossref pagination safety limit reached")




async def fetch_ecml(client, label, year_from, year_to, *, on_page=None, max_pages=200):
    """Enumerate exact containers and resolve publisher parent-book evidence.

    Completeness here covers these Crossref inventories, NOT all proceedings
    ever published. The extra imprint year accommodates delayed publication.
    No PDF/book content is requested.
    """
    if label != "ECML-PKDD":
        raise ValueError("Unsupported conference inventory")
    parents, seen, result = {}, set(), []
    limiter = AsyncTokenBucket(0.5)
    for page, title in enumerate(ECML_CONTAINERS, 1):
        await limiter.acquire()
        items = await fetch_container(client, title, year_from, min(year_to + 1, 2100), max_pages=max_pages)
        accepted = []
        for original in items:
            doi = normalize_doi(original.get("DOI")) or ""
            if not re.fullmatch(r"10\.1007/978-[\d-]+_\d+", doi) or doi in seen:
                continue
            parent_doi = doi.rsplit("_", 1)[0]
            if parent_doi not in parents:
                await limiter.acquire()
                for attempt in range(3):
                    response = await client.get(f"{API}/works/{parent_doi}")
                    if response.status_code not in (429, 502, 503, 504) or attempt == 2:
                        break
                    await asyncio.sleep(10 * (attempt + 1))
                response.raise_for_status()
                parent = response.json().get("message")
                if not isinstance(parent, dict) or normalize_doi(parent.get("DOI")) != parent_doi:
                    raise ValueError("ECML parent-book response identity mismatch")
                parents[parent_doi] = {key: parent.get(key) for key in ("DOI", "title", "subtitle", "type", "published-print", "published-online")}
            item = {**original, "_ecml_parent": parents[parent_doi]}
            year = ecml_conference_year(item)
            if year and year_from <= year <= year_to:
                accepted.append(item)
                seen.add(doi)
        result.extend(accepted)
        if on_page:
            # No global advertised paper count is available across books.
            on_page(label + ": " + title, page, len(result), None, accepted)
    return result


async def fetch_configured_inventory(client, venue, year, *, cache=None):
    """Supplement a scheduled unit with exact publisher identities.

    Exhausting this source never certifies the unit's global completeness.
    A small run-owned cache avoids fetching shared publisher prefixes twice.
    """
    cache = cache if cache is not None else {}
    requests = []
    if venue.type == "journal":
        requests = [(issn, fetch_journal) for issn in sorted({issn for issn, _ in journal_identities(venue)})]
    elif venue.abbr == "ICRA":
        requests = [(f"{year} IEEE International Conference on Robotics and Automation (ICRA)", fetch_container)]
    elif venue.abbr == "ECML-PKDD":
        requests = [("ECML-PKDD", fetch_ecml)]
    else:
        prefix = {"AAAI": "10.1609", "ICAPS": "10.1609", "IJCAI": "10.24963", "KR": "10.24963", "ECAI": "10.3233"}.get(venue.abbr)
        if prefix: requests = [(prefix, fetch_prefix)]
    result, seen = [], set()
    # Include early-access deposits around a formal publication year; filter
    # records again by the publisher's issue/conference year, not deposit year.
    for label, fetch in requests:
        key = (label, year)
        if key not in cache:
            cache[key] = await fetch(client, label, max(2000, year-2), min(2100, year+1))
        for item in cache[key]:
            if identify_venue(item, {venue.abbr: venue}) is None:
                continue
            raw = item_to_raw(item)
            if raw and raw.year == year and raw.doi not in seen:
                raw.extra["crossref_item"] = item
                result.append(raw)
                seen.add(raw.doi)
    return result
