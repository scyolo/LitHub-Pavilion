"""Official CoNEXT/PODS lists resolved by exact publisher serial, title, and authors."""

import re

from app.cleaning import clean_author_name, normalize_doi, normalize_title
from app.collectors.crossref import metadata_text, publication_date
from app.collectors.usenix_catalog import Tree
from app.services.publication_identity import (
    _name_match,
    _parts,
    publication_authors_match,
)

SPECS = {
    "CoNEXT": ("2834-5509", "Proceedings of the ACM on Networking"),
    "PODS": ("2836-6573", "Proceedings of the ACM on Management of Data"),
}


def parse_publication_list(text, abbr, year):
    if abbr not in SPECS or not 2023 <= year <= 2026:
        raise ValueError("Unsupported publication list scope")
    tree = Tree()
    tree.feed(text)
    heading = re.compile(
        re.escape(abbr) + r"\s+" + str(year) + r"\s*:?[ ]*(?:Accepted|Research) Papers",
        re.IGNORECASE,
    )
    heading_matches = tree.root.find(
        lambda n: (
            n.tag in ("h1", "h2")
            and heading.fullmatch(re.sub(r"\s+", " ", n.text()).strip())
        )
    )
    explicit_page_year = (
        abbr == "PODS"
        and tree.root.find(
            lambda n: (
                n.tag == "title"
                and f"The {year} ACM SIGMOD/PODS Conference:" in n.text()
            )
        )
        and tree.root.find(
            lambda n: n.tag == "h1" and n.text().strip() == "Accepted Papers for PODS"
        )
    )
    if not heading_matches and not explicit_page_year:
        raise ValueError("Official source/year heading mismatch")
    root = tree.root
    if abbr == "PODS":
        containers = root.find(lambda n: n.attrs.get("id") == "maincontent")
        if len(containers) != 1:
            raise ValueError("PODS paper list body missing")
        root = containers[0]

    def author_text(node):
        if isinstance(node, str):
            return node
        if node.tag in ("b", "strong", "em"):
            return ""
        return "".join(author_text(child) for child in node.children)

    records = []
    seen = set()
    for node in root.find(lambda n: n.tag == "li"):
        titles = node.find(lambda n: n.tag in ("b", "strong"))
        if not titles:
            continue
        if len(titles) != 1:
            raise ValueError("Ambiguous title in official list")
        title = re.sub(r"\s+", " ", titles[0].text()).strip()
        names = [
            clean_author_name(x.strip())
            for x in re.split(r",|\band\b", author_text(node))
            if x.strip()
        ]
        if not names or not title or title in seen:
            raise ValueError("Missing or duplicated paper identity")
        seen.add(title)
        records.append(
            {"title": title, "authors": names, "conference": abbr, "event_year": year}
        )
    if not records:
        raise ValueError("No research papers in official list")
    return records


def match_registry_paper(paper, candidates, abbr):
    issn, serial = SPECS[abbr]
    matches = {}
    for item in candidates:
        doi = normalize_doi(item.get("DOI")) or ""
        year, _ = publication_date(item)
        if (
            item.get("type") != "journal-article"
            or issn not in (item.get("ISSN") or [])
            or item.get("container-title") != [serial]
            or not re.fullmatch(r"10\.1145/[0-9]+", doi)
            or not 2023 <= year <= 2026
        ):
            continue
        titles = item.get("title") or []
        if len(titles) != 1 or normalize_title(
            metadata_text(titles[0])
        ) != normalize_title(paper["title"]):
            continue
        authors = [
            clean_author_name(" ".join(filter(None, (a.get("given"), a.get("family")))))
            for a in item.get("author", [])
        ]
        valid = publication_authors_match(paper["authors"], authors)
        if (
            not valid
            and abbr == "CoNEXT"
            and len(authors) == len(paper["authors"])
            and len(authors) >= 2
        ):
            surnames = [_parts(a)[0] for a in authors]
            valid = len(set(surnames)) == len(surnames) and all(
                _name_match(a, b)[0] for a, b in zip(paper["authors"], authors)
            )
        if valid:
            matches[doi] = item
    return next(iter(matches.values())) if len(matches) == 1 else None
