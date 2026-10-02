"""Official Performance program: collect long-paper identities, never presentation PDFs."""

import re

from app.collectors.publisher_toc import _raw
from app.collectors.usenix_catalog import Tree


def parse_program(text, year):
    tree = Tree()
    tree.feed(text)
    if not 2023 <= year <= 2026:
        raise ValueError("Unsupported Performance edition")
    titles = tree.root.find(lambda n: n.tag == "title")
    edition = tree.root.find(
        lambda n: (
            n.tag == "input"
            and n.attrs.get("name") == "conference"
            and n.attrs.get("value") == f"performance{year}"
        )
    )
    if not edition or not any("IFIP WG 7.3 Performance" in n.text() for n in titles):
        raise ValueError("Performance source/year mismatch")
    if year == 2023:
        return _parse_2023(tree, year)
    selected = []
    seen = set()
    section = None
    shorts = 0
    for node in tree.root.find(lambda n: n.tag in ("p", "li")):
        text = re.sub(r"\s+", " ", node.text()).strip()
        if node.tag == "p":
            if re.match(r"Session [0-9]", text):
                section = text
            continue
        marker = re.search(r"\(paper #(\d+)\)", text)
        if not marker:
            continue
        if not section:
            raise ValueError("Paper outside known session")
        if marker[1] in seen:
            raise ValueError("Duplicate Performance paper identity")
        seen.add(marker[1])
        if "short papers" in section.lower():
            shorts += 1
            continue
        em = node.find(lambda n: n.tag == "em")
        title = "".join(n.text() for n in em).strip()
        author_text = re.split(r"\s+-\s*", text, maxsplit=1)[0]
        if not title or author_text == text:
            raise ValueError("Performance title/author layout mismatch")
        authors = [n.strip() for n in author_text.split(",") if n.strip()]
        raw = _raw(
            f"https://performance{year}.sciencesconf.org/resource/page/id/3#paper-{marker[1]}",
            title,
            authors,
            year,
        )
        raw.extra["provenance"] = "official_conference_list"
        selected.append(raw)
    if not selected:
        raise ValueError("No Performance long-paper records parsed")
    return selected, {
        "long_papers": len(selected),
        "short_papers": shorts,
        "listed_papers": len(seen),
        "complete": False,
    }


def _parse_2023(tree, year):
    roots = tree.root.find(lambda n: n.attrs.get("id") == "page")
    if len(roots) != 1:
        raise ValueError("Missing program body")
    records = []
    seen = set()

    def pieces(node):
        if isinstance(node, str):
            return node
        if node.tag == "br":
            return "\x1f"
        return "".join(pieces(child) for child in node.children)

    for node in roots[0].find(lambda n: n.tag == "li"):
        text = pieces(node)
        parts = text.split("\x1f")
        if len(parts) != 2:
            raise ValueError("Unrecognized Performance title/author boundary")
        title = re.sub(r"\s+", " ", parts[0]).strip()
        authors = [
            re.sub(r"\s+", " ", n).strip() for n in parts[1].split(",") if n.strip()
        ]
        if not title or not authors or title in seen:
            raise ValueError("Invalid or duplicate program record")
        seen.add(title)
        raw = _raw(
            "https://performance2023.sciencesconf.org/resource/page/id/6",
            title,
            authors,
            year,
        )
        raw.extra["provenance"] = "official_conference_list"
        records.append(raw)
    if not records:
        raise ValueError("No Performance program papers")
    return records, {
        "long_papers": len(records),
        "short_papers": 0,
        "listed_papers": len(records),
        "complete": False,
    }
