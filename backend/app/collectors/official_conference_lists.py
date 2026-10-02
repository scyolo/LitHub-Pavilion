"""Official main-conference lists used to associate already identified journal articles."""

import re

from app.collectors.publisher_toc import _raw


def parse_vis(items, year):
    if not isinstance(items, list):
        raise ValueError("VIS paper list must be an array")  # noqa: TRY004 - malformed remote data
    records = []
    for item in items:
        if (
            item.get("paper_type") != "full"
            or item.get("event_title") != "VIS Full Papers"
        ):
            continue
        if not str(item.get("time_stamp", "")).startswith(str(year) + "-"):
            continue
        title = item.get("title")
        authors = [a["name"] for a in item.get("authors", []) if a.get("name")]
        uid = item.get("id", "")
        if not title or not authors or not re.fullmatch(r"[A-Za-z0-9_-]+", uid):
            raise ValueError("VIS main paper identity incomplete")
        raw = _raw(
            f"https://ieeevis.org/year/{year}/program/paper_{uid}.html",
            title,
            authors,
            year,
            doi=item.get("doi"),
        )
        raw.extra["provenance"] = "official_conference_list"
        records.append(raw)
    return records


def parse_ismb(text, year):
    from app.collectors.usenix_catalog import Tree

    tree = Tree()
    tree.feed(text)
    if not tree.root.find(
        lambda n: (
            n.tag in ("h1", "h2", "h3")
            and "Proceedings Track Presentations" in n.text()
        )
    ):
        raise ValueError("Not the official ISMB proceedings track")
    nodes = tree.root.find(
        lambda n: (n.tag == "div" and n.has_class("well")) or n.tag == "ul"
    )
    records = []
    for i, node in enumerate(nodes[:-1]):
        if not node.has_class("well"):
            continue
        following = nodes[i + 1]
        if following.tag != "ul":
            raise ValueError("Missing ISMB author list")
        authors = [
            n.text().split(",", 1)[0].strip()
            for n in following.find(lambda n: n.tag == "li")
        ]
        if not authors:
            raise ValueError("Missing ISMB authors")
        raw = _raw(
            f"https://www.iscb.org/ismb{year}/whats-happening/proceedings",
            node.text().strip(),
            authors,
            year,
        )
        raw.extra["provenance"] = "official_conference_list"
        records.append(raw)
    return records


def parse_hipeac_session(data, year):
    if (
        data.get("type", {}).get("value") != "Paper Track"
        or data.get("event", {}).get("name") != f"HiPEAC {year}"
    ):
        return []
    if not data.get("start_at", "").startswith(str(year) + "-"):
        return []
    records = []
    for title, authors, doi in re.findall(
        r"^- _(.+?)_\s+(.+?)\s+<?https://(?:dl\.acm\.org/doi/|doi\.org/)(10\.1145/[0-9]+)>?",
        data.get("description", ""),
        re.MULTILINE,
    ):
        names = [
            n.strip(" .") for n in re.split(r",|\band\b", authors) if n.strip(" .")
        ]
        raw = _raw("https://doi.org/" + doi, title, names, year, doi=doi)
        raw.extra["provenance"] = "official_conference_list"
        records.append(raw)
    return records
