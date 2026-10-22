"""Enrich existing publications from exact, public conference-program evidence."""

import re
from collections import defaultdict
from urllib.parse import parse_qs, urljoin, urlsplit

from app.api.serializers import abstract_text, safe_http_url
from app.cleaning import normalize_doi, normalize_title
from app.collectors.publisher_toc import _raw
from app.models import Paper
from app.services.paper_store import same_authors


PROGRAM_HOSTS = {
    'ICML': 'icml.cc', 'NeurIPS': 'neurips.cc', 'ICLR': 'iclr.cc',
    'CVPR': 'cvpr.thecvf.com', 'ICCV': 'iccv.thecvf.com',
}


def _cvf_program_abstracts(rows, venue, year):
    """CVF's published main-paper lists have distinct, year-specific fields."""
    group = f'thecvf.com/{venue}/{year}/Conference'
    sources = {'https://openreview.net/group?id=' + group}
    if (venue, year) == ('ICCV', 2025):
        sources.add(group)
    records = {}
    for row in rows:
        if row.get('sourceurl') not in sources or row.get('eventtype') != 'Poster':
            continue
        decision = str(row.get('decision') or '').casefold()
        accepted = decision.startswith('accept') or (
            (venue, year) == ('ICCV', 2025) and decision in {'poster', 'highlight', 'oral'}
        ) or ((venue, year) == ('CVPR', 2025) and row.get('decision') is None)
        virtual = row.get('virtualsite_url') or ''
        if not accepted or not re.fullmatch(rf'/virtual/{year}/poster/[0-9]+', virtual):
            continue
        abstract = abstract_text(row.get('abstract'))
        authors = [a.get('fullname') for a in row.get('authors', []) if a.get('fullname')]
        if not abstract or not 80 <= len(abstract) <= 100000 or not authors:
            continue
        url = 'https://' + PROGRAM_HOSTS[venue] + virtual
        raw = _raw(url, row.get('name', ''), authors, year, abstract=abstract)
        if not raw.title.strip():
            continue
        if url in records and (
            records[url].title != raw.title or records[url].authors != raw.authors
            or records[url].extra['abstract'] != abstract
        ):
            raise ValueError('Conflicting program publication identity')
        records[url] = raw
    return list(records.values())


def program_abstracts(data, venue, year):
    if venue not in PROGRAM_HOSTS or not 2023 <= year <= 2026:
        raise ValueError("Unsupported conference/year")
    rows = data.get("results")
    if not isinstance(rows, list) or data.get("count") != len(rows) or data.get("next"):
        raise ValueError("Incomplete public program")
    if venue in {'CVPR', 'ICCV'}:
        return _cvf_program_abstracts(rows, venue, year)
    groups = {f"https://openreview.net/group?id={venue}.cc/{year}/Conference"}
    if venue == "ICML":
        groups.add(
            f"https://openreview.net/group?id=ICML.cc/{year}/Position_Paper_Track"
        )
    if venue == "NeurIPS":
        groups.update(
            f"https://openreview.net/group?id=NeurIPS.cc/{year}/{track}"
            for track in (
                "Track/Datasets_and_Benchmarks",
                "Datasets_and_Benchmarks_Track",
                "Position_Paper_Track",
            )
        )
    result = {}
    for row in rows:
        if (
            row.get("sourceurl") not in groups
            or row.get("eventtype") != "Poster"
            or not str(row.get("decision", "")).lower().startswith("accept")
        ):
            continue
        url = safe_http_url(row.get("paper_url"))
        if not url:
            virtual = row.get("virtualsite_url") or ""
            if re.fullmatch(rf"/virtual/{year}/poster/[0-9]+", virtual):
                host = "neurips" if venue == "NeurIPS" else venue.lower()
                url = urljoin(f"https://{host}.cc/", virtual)
        if not url:
            continue
        parsed = urlsplit(url)
        if parsed.hostname == "openreview.net":
            ids = parse_qs(parsed.query).get("id", [])
            if (
                parsed.path != "/forum"
                or len(ids) != 1
                or not re.fullmatch(r"[A-Za-z0-9_-]+", ids[0])
            ):
                continue
            url = "https://openreview.net/forum?id=" + ids[0]
        elif parsed.hostname in {"icml.cc", "neurips.cc", "iclr.cc"}:
            if not re.fullmatch(rf"/virtual/{year}/poster/[0-9]+", parsed.path):
                continue
        elif parsed.hostname not in {
            "proceedings.mlr.press",
            "papers.nips.cc",
            "papers.neurips.cc",
            "proceedings.neurips.cc",
        } or not parsed.path.endswith(".html"):
            continue
        abstract = abstract_text(row.get("abstract"))
        if not abstract or not 80 <= len(abstract) <= 100000:
            continue
        authors = [
            a.get("fullname") for a in row.get("authors", []) if a.get("fullname")
        ]
        raw = _raw(url, row.get("name", ""), authors, year, abstract=abstract)
        if not raw.title.strip() or not raw.authors:
            continue
        if url in result and (
            result[url].title != raw.title
            or result[url].authors != raw.authors
            or result[url].extra["abstract"] != abstract
        ):
            raise ValueError("Conflicting program publication identity")
        result[url] = raw
    return list(result.values())


def fill_program_abstracts(db, venue, year, records, source_url):
    candidates = (
        db.query(Paper)
        .filter(
            Paper.venue_id == venue.id, Paper.year == year, Paper.venue_confirmed == 1
        )
        .all()
    )
    by_title = defaultdict(list)
    for paper in candidates:
        by_title[paper.title_norm].append(paper)
    filled, rejected = [], []
    for raw in records:
        matches = by_title.get(normalize_title(raw.title), [])
        if not matches:
            continue
        verified = [
            p for p in matches
            if (not raw.doi or normalize_doi(p.doi) == normalize_doi(raw.doi))
            and same_authors(db, p, raw, publisher_verified=True)
        ]
        if len(verified) != 1:
            rejected.append(
                {
                    "url": raw.official_url,
                    "title": raw.title,
                    "reason": "publication identity/title/complete-author match is absent or ambiguous",
                }
            )
            continue
        paper = verified[0]
        if abstract_text(paper.abstract) is not None:
            continue
        paper.abstract = raw.extra["abstract"]
        evidence = f"Abstract verified against {source_url}; exact venue/year/title/complete authors; program paper {raw.official_url}"
        if evidence not in (paper.note or ""):
            paper.note = (paper.note + "\n" if paper.note else "") + evidence
        filled.append(paper.id)
    db.flush()
    return {"filled": filled, "rejected": rejected}
