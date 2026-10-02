"""SPM official migrated program: main paper sessions only, no award/keynote talks."""

import re

from app.collectors.publisher_toc import _raw
from app.collectors.usenix_catalog import Tree


def parse_spm_program(text, year):
    if year != 2023:
        raise ValueError("Only verified SPM program edition supported")
    url = "https://sites.google.com/view/spm-2023/program"
    tree = Tree()
    tree.feed(text)
    if not tree.root.find(
        lambda n: (
            n.tag == "meta"
            and n.attrs.get("property") == "og:url"
            and n.attrs.get("content") == url
        )
    ):
        raise ValueError("SPM official source mismatch")
    selected = False
    records = []
    seen = set()
    for node in tree.root.find(lambda n: n.tag == "p"):
        text = re.sub(r"\s+", " ", node.text()).strip()
        if text.startswith("SESSION:"):
            selected = True
            continue
        if re.match(
            r"(?:INVITED|BEZIER|BEST PAPER|CLOSING|WEDNESDAY|THURSDAY|FRIDAY)", text
        ):
            selected = False
            continue
        if not selected or not text:
            continue
        parts = re.split(r"\s+-\s+", text.lstrip("- "), maxsplit=1)
        if len(parts) != 2:
            raise ValueError("SPM paper author/title boundary missing")
        authors = [name.strip(" ,") for name in parts[0].split(",") if name.strip(" ,")]
        title = parts[1].strip()
        if not authors or not title or title in seen:
            raise ValueError("Invalid/duplicate SPM paper")
        seen.add(title)
        raw = _raw(url, title, authors, year)
        raw.extra["provenance"] = "official_conference_list"
        records.append(raw)
    if not records:
        raise ValueError("No SPM main program papers")
    return records
