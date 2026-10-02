"""Explicit registry-verified serial continuations and alternate ISSNs, never fuzzy matching."""

import json
from pathlib import Path

from app.cleaning import normalize_title

SOURCES = json.loads(
    (
        Path(__file__).resolve().parents[3] / "seeds/journal_serial_provenance.json"
    ).read_text(encoding="utf-8")
)["sources"]


def serial_sources(venue):
    if getattr(venue, "type", None) != "journal":
        return []
    for source in SOURCES:
        if (
            getattr(venue, "abbr", None) == source["venue"]
            and venue.issn == source["catalog_issn"]
            and normalize_title(venue.name) == normalize_title(source["catalog_name"])
        ):
            return [dict(record) for record in source["records"]]
    return []


def valid_serial_item(item, spec):
    from app.collectors.crossref import metadata_text, publication_date

    if item.get("type") != "journal-article" or spec["issn"] not in (
        item.get("ISSN") or []
    ):
        return False
    titles = item.get("container-title") or []
    if len(titles) != 1 or normalize_title(metadata_text(titles[0])) != normalize_title(
        spec["title"]
    ):
        return False
    year, _ = publication_date(item)
    return spec["year_from"] <= year <= spec["year_to"]
