"""Exact Springer parent-book evidence for CCF conference chapters; metadata only."""

import json
import re
from pathlib import Path

from app.cleaning import normalize_doi, normalize_title

SPECS = json.loads(
    (
        Path(__file__).resolve().parents[3] / "seeds/springer_conference_books.json"
    ).read_text(encoding="utf-8")
)
EXCLUDED = re.compile(
    r"\b(workshops?|tutorials?|doctoral|posters?|companion|satellite|summaries|abstracts)\b",
    re.IGNORECASE,
)


def book_year(parent, abbr):
    if abbr not in SPECS or parent.get("type") != "book":
        return None
    doi = normalize_doi(parent.get("DOI")) or ""
    if not re.fullmatch(r"10\.1007/978-[0-9-]+", doi):
        return None
    titles = parent.get("title") or []
    if len(titles) != 1 or not re.fullmatch(SPECS[abbr][1], normalize_title(titles[0])):
        return None
    subtitle = " ".join(parent.get("subtitle") or [])
    whole = titles[0] + " " + subtitle
    if EXCLUDED.search(whole) or "proceedings" not in subtitle.lower():
        return None
    if not re.search(
        r"(?<![A-Za-z])" + re.escape(abbr) + r"(?![A-Za-z])", whole, re.IGNORECASE
    ):
        return None
    years = {int(y) for y in re.findall(r"\b(20\d{2})\b", whole)}
    if len(years) != 1:
        return None
    year = years.pop()
    return year if 2023 <= year <= 2026 else None


def chapter_year(item, venue):
    if getattr(venue, "type", None) != "conf" or getattr(
        venue, "ccf_level", None
    ) not in ("A", "B"):
        return None
    parent = item.get("_catalog_book_parent") or {}
    year = book_year(parent, getattr(venue, "abbr", None))
    if year is None or item.get("type") != "book-chapter":
        return None
    doi = normalize_doi(item.get("DOI")) or ""
    parent_doi = normalize_doi(parent.get("DOI")) or ""
    if not re.fullmatch(re.escape(parent_doi) + r"_\d+", doi):
        return None
    if parent["title"][0] not in (item.get("container-title") or []):
        return None
    return year
