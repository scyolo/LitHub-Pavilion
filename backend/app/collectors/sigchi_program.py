"""Public SIGCHI main-paper programs, cross-checked against publisher journal metadata."""

import re
from urllib.parse import urlsplit

from app.cleaning import clean_author_name, normalize_doi, normalize_title
from app.collectors.crossref import metadata_text, publication_date
from app.services.publication_identity import publication_authors_match

HOSTS = {
    "CSCW": {"cscw.acm.org"},
    "ISS": {"iss.acm.org"},
    "MobileHCI": {"mobilehci.acm.org"},
    "GROUP": {"group.acm.org"},
}


def program_papers(data, abbr, year):
    publication = data.get("publicationInfo")
    if publication is not None and (
        publication.get("publicationStatus") != "PUBLISHED"
        or publication.get("isDraft") is not False
    ):
        raise ValueError("Unpublished program cannot prove conference membership")
    conf = data.get("conference") or {}
    if (
        abbr not in HOSTS
        or conf.get("shortName", "").casefold() != abbr.casefold()
        or conf.get("year") != year
        or not 2023 <= year <= 2026
        or (urlsplit(conf.get("url") or "").hostname or "").lower() not in HOSTS[abbr]
    ):
        raise ValueError("Official program conference identity/year mismatch")
    types = {
        t["id"]
        for t in data.get("contentTypes", [])
        if t.get("name") in {"Paper", "Full Paper", "Research Paper"}
    }
    people = {
        p["id"]: clean_author_name(
            " ".join(
                filter(
                    None,
                    (p.get("firstName"), p.get("middleInitial"), p.get("lastName")),
                )
            )
        )
        for p in data.get("people", [])
    }
    records = []
    seen = set()
    for content in data.get("contents", []):
        if content.get("typeId") not in types or content.get("isBreak"):
            continue
        identity = content.get("id")
        title = content.get("title")
        authors = [people.get(a.get("personId")) for a in content.get("authors", [])]
        if (
            type(identity) is not int
            or identity in seen
            or not isinstance(title, str)
            or not title.strip()
            or not authors
            or not all(authors)
        ):
            raise ValueError("Official main paper lacks unique identity/title/authors")
        seen.add(identity)
        records.append(
            {
                "program_id": identity,
                "title": title,
                "authors": authors,
                "conference": abbr,
                "event_year": year,
            }
        )
    return records


def hci_title_key(title, conference):
    title = metadata_text(title)
    # Only the publisher's MobileHCI manuscript code is discarded for matching.
    if conference == "MobileHCI":
        title = re.sub(r"\s+MHCI[0-9]{3,4}\s*$", "", title)
    return normalize_title(title)


def match_hci_publication(paper, candidates):
    matches = {}
    for item in candidates:
        doi = normalize_doi(item.get("DOI")) or ""
        year, _ = publication_date(item)
        if (
            item.get("type") != "journal-article"
            or "2573-0142" not in (item.get("ISSN") or [])
            or item.get("container-title")
            != ["Proceedings of the ACM on Human-Computer Interaction"]
            or not re.fullmatch(r"10\.1145/[0-9]+", doi)
            or not 2023 <= year <= 2026
        ):
            continue
        titles = item.get("title") or []
        if len(titles) != 1 or hci_title_key(
            titles[0], paper.get("conference")
        ) != normalize_title(paper["title"]):
            continue
        authors = [
            clean_author_name(" ".join(filter(None, (a.get("given"), a.get("family")))))
            for a in item.get("author", [])
        ]
        if publication_authors_match(paper["authors"], authors):
            matches[doi] = item
    return next(iter(matches.values())) if len(matches) == 1 else None
