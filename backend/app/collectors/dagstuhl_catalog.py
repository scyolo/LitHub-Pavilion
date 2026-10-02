"""DataCite-registered Dagstuhl main proceedings; retrieve metadata, never media."""

import re

from app.cleaning import normalize_doi
from app.collectors.publisher_toc import _raw
from app.services.publication_admission import nonresearch_title

SERIES = {
    name: "LIPIcs." + name
    for name in ("SoCG", "ECOOP", "CCC", "ESA", "ICALP", "CONCUR", "ICDT", "SAT", "CP")
}


def parse_record(item, abbr, year):
    if abbr not in SERIES or not 2023 <= year <= 2026:
        return None
    attr = item.get("attributes") or {}
    doi = normalize_doi(attr.get("doi")) or ""
    parent = f"10.4230/{SERIES[abbr]}.{year}".lower()
    if (
        not re.fullmatch(re.escape(parent) + r"\.[1-9]\d*", doi)
        or normalize_doi(item.get("id")) != doi
    ):
        return None
    if not str(attr.get("publisher", "")).startswith("Schloss Dagstuhl"):
        return None
    if (attr.get("types") or {}).get("resourceTypeGeneral") != "ConferencePaper":
        return None
    if normalize_doi((attr.get("container") or {}).get("identifier")) != parent:
        return None
    url = attr.get("url") or ""
    if url.lower() != "https://drops.dagstuhl.de/entities/document/" + doi:
        return None
    titles = attr.get("titles") or []
    if len(titles) != 1:
        return None
    title = titles[0].get("title") or ""
    if nonresearch_title(title) or re.search(
        r"\b(invited talk|keynote|front matter|preface|table of contents)\b",
        title,
        re.IGNORECASE,
    ):
        return None
    authors = [c.get("name") for c in attr.get("creators", []) if c.get("name")]
    if not authors:
        return None
    abstract = next(
        (
            d["description"]
            for d in attr.get("descriptions", [])
            if d.get("descriptionType") == "Abstract"
        ),
        None,
    )
    raw = _raw(url, title, authors, year, doi=doi, abstract=abstract)
    raw.extra["registry_parent"] = parent
    return raw
