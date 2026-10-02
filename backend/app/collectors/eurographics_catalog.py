"""Eurographics-owned library CGF conference issues; exact metadata only."""

import re

from app.collectors.publisher_toc import _raw, plain
from app.services.publication_admission import nonresearch_title

NAMES = {
    "Eurographics": r"EG|Eurographics",
    "EuroVis": r"EuroVis",
    "EGSR": r"Rendering",
    "SGP": r"Geometry Processing",
    "PG": r"Pacific Graphics",
    "SCA": r"ACM SIGGRAPH / Eurographics Symposium on Computer Animation",
}


def values(meta, key):
    return [v.get("value", "") for v in meta.get(key, [])]


def collection_identity(collection):
    m = re.fullmatch(r"(\d+)-Issue (\d+)", collection.get("name", ""))
    if not m:
        return None
    meta = collection.get("metadata") or {}
    description = " ".join(values(meta, "dc.description.abstract"))
    if not description.strip():
        html = " ".join(values(meta, "dc.description"))
        titles = re.findall(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        description = " ".join(plain(t) for t in titles)
    for abbr, pattern in NAMES.items():
        found = re.fullmatch(
            "(?:"
            + pattern
            + r") (20\d{2})(?:\s*-\s*(?:Conference Issue|Conference Proceedings|Symposium Proceedings)\.?)?",
            description.strip(),
            re.IGNORECASE,
        )
        if (
            found
            and 2023 <= int(found[1]) <= 2026
            and int(m[1]) == int(found[1]) - 1981
        ):
            return abbr, int(found[1]), m[1], m[2]
    return None


def parse_item(item, year, volume, issue, *, verified_membership=False):
    meta = item.get("metadata") or {}
    for key, expected in [
        ("dc.description.volume", volume),
        ("dc.description.number", issue),
    ]:
        actual = values(meta, key)
        if actual != [expected] and not (not actual and verified_membership):
            return None
    if values(meta, "dc.date.issued") not in ([str(year)], [f"{year}-01-01"]):
        return None
    if not set(values(meta, "dc.identifier.issn")) & {"1467-8659", "0167-7055"}:
        return None
    if not any(
        "Eurographics" in p and "Wiley" in p for p in values(meta, "dc.publisher")
    ):
        return None
    titles = values(meta, "dc.title")
    dois = values(meta, "dc.identifier.doi")
    if (
        len(titles) != 1
        or len(dois) != 1
        or not re.fullmatch(r"10\.1111/cgf\.[0-9]+", dois[0], re.IGNORECASE)
    ):
        return None
    title = titles[0]
    if nonresearch_title(title) or re.search(
        r"\b(issue information|frontmatter|front matter|preface|editorial)\b",
        title,
        re.IGNORECASE,
    ):
        return None
    authors = [
        v["value"]
        for v in sorted(
            meta.get("dc.contributor.author", []), key=lambda v: v.get("place", 0)
        )
        if v.get("value")
    ]
    if not authors:
        return None
    return _raw(
        "https://doi.org/" + dois[0],
        title,
        authors,
        year,
        doi=dois[0],
        abstract=next(iter(values(meta, "dc.description.abstract")), None),
    )
