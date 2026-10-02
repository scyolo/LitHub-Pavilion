"""Strict title/DOI/ordered author extraction from official ACM OpenTOC HTML."""

import re

from app.cleaning import normalize_doi
from app.collectors.usenix_catalog import Tree


def parse_open_toc(page, parent_doi, heading):
    if not re.fullmatch(r"10\.1145/[0-9]+", parent_doi):
        raise ValueError("Invalid proceedings identity")
    tree = Tree()
    tree.feed(page)
    if not any(
        node.text().strip() == heading
        for node in tree.root.find(lambda n: n.tag == "h1")
    ):
        raise ValueError("OpenTOC conference heading mismatch")
    parents = tree.root.find(
        lambda n: (
            n.tag == "a"
            and n.attrs.get("href")
            == "https://dl.acm.org/doi/proceedings/" + parent_doi
        )
    )
    if len(parents) != 1:
        raise ValueError("OpenTOC parent proceedings mismatch")
    regions = tree.root.find(lambda n: n.attrs.get("id") == "DLtoc")
    if len(regions) > 1:
        raise ValueError("Ambiguous OpenTOC region")
    region = regions[0] if regions else tree.root
    rows, pending, seen, section = [], None, set(), ""
    for node in region.find(
        lambda n: n.tag in ("h2", "h3") or (n.tag == "ul" and n.has_class("DLauthors"))
    ):
        if node.tag == "h2":
            if pending is not None:
                raise ValueError("OpenTOC paper without authors")
            section = node.text().strip()
        elif node.tag == "h3":
            links = node.find(lambda n: n.tag == "a" and n.has_class("DLtitleLink"))
            if pending is not None or len(links) != 1:
                raise ValueError("OpenTOC ambiguous paper title")
            doi = normalize_doi(
                links[0]
                .attrs.get("href", "")
                .replace("https://dl.acm.org/doi/", "https://doi.org/")
            )
            if (
                not doi
                or not re.fullmatch(re.escape(parent_doi) + r"\.[0-9]+", doi)
                or doi in seen
            ):
                raise ValueError("OpenTOC foreign or duplicate DOI")
            seen.add(doi)
            pending = {"doi": doi, "title": links[0].text().strip(), "section": section}
        else:
            if pending is None:
                raise ValueError("OpenTOC orphan author list")
            names = [
                n.text().strip()
                for n in node.find(lambda n: n.tag == "li" and n.has_class("nameList"))
            ]
            if not names or not all(names) or not pending["title"]:
                raise ValueError("OpenTOC title/author missing")
            rows.append({**pending, "authors": names})
            pending = None
    if pending is not None or not rows:
        raise ValueError("OpenTOC incomplete inventory")
    return rows


def restore_verified_subtitles(items, official):
    """Join explicit publisher title/subtitle only when the same DOI's TOC agrees."""
    from app.cleaning import normalize_title
    from app.collectors.crossref import metadata_text

    by_doi = {row["doi"]: row["title"] for row in official}
    restored, count = [], 0
    for item in items:
        titles, subtitles = item.get("title") or [], item.get("subtitle") or []
        expected = by_doi.get(normalize_doi(item.get("DOI")))
        if expected and len(titles) == len(subtitles) == 1:
            joined = metadata_text(titles[0]) + ": " + metadata_text(subtitles[0])
            if normalize_title(joined) == normalize_title(expected):
                item = {**item, "title": [expected]}
                count += 1
        restored.append(item)
    return restored, count
