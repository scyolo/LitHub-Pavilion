"""Bounded query conveniences; never used for publication identity matching."""

import json
import re
import unicodedata

from app.config import settings

ALIASES = json.loads(
    (settings.seeds_dir / "query_aliases.json").read_text("utf8")
)
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def query_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def keyword_query(value):
    if not isinstance(value, str) or len(value) > 300:
        return value
    return ALIASES["keywords"].get(query_key(value), value)


def query_topic(value, mode, directions):
    if (
        not isinstance(value, str)
        or len(value) > 300
        or mode == "exact"
        or not CJK.search(value)
    ):
        return None
    key = query_key(value)
    code = ALIASES["topics"].get(key)
    for direction in directions:
        if direction.enabled == 1 and (
            direction.code == code or query_key(direction.name) == key
        ):
            return direction
    return None
