"""Narrow, sourced publisher errata; never fuzzy or global title replacements."""
import json
from pathlib import Path

from app.cleaning import normalize_title

CORRECTIONS = json.loads(Path(__file__).with_suffix(".json").read_text("utf-8"))


def correct_catalogue_title(raw):
    for item in CORRECTIONS:
        if (raw.official_url == item["publisher_key"] and raw.doi == item["doi"]
                and raw.year == item["year"] and raw.authors == item["catalogue_authors"]
                and normalize_title(raw.title) == normalize_title(item["catalogue_title"])):
            raw.extra["publisher_title_correction"] = item["source"]
            raw.extra["catalogue_title"] = raw.title
            raw.title = item["title"]
            break
    return raw
