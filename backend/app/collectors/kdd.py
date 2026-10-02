"""KDD's published research-track catalogue: explicit article DOIs, no PDFs.

Edition URLs and proceeding identities are deliberately pinned to observed
official catalogues. Do not guess a URL or reuse last year's parsing for a new
edition; workshops/applied-data-science pages are not this inventory.
"""
import re
from html.parser import HTMLParser

from app.collectors.publisher_toc import _raw, _validate, plain

CATALOGUES = {
    2025: "https://www.kdd.org/kdd2025/research-track-papers-2/",
}
PROCEEDINGS = {2025: {"10.1145/3690624", "10.1145/3711896"}}


class _CatalogueCells(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = []
        self.parts = None
        self.table_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table_depth += 1
        if tag == "td" and self.table_depth:
            if self.parts is not None:
                raise ValueError("Nested KDD catalogue cells")
            self.parts = []
        elif tag == "br" and self.parts is not None:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.parts is not None:
            self.cells.append("".join(self.parts).strip())
            self.parts = None
        if tag == "table":
            self.table_depth -= 1


def _authors(value):
    depth = 0
    parts = []
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Invalid KDD author affiliation")
        elif not depth:
            parts.append(character)
    if depth:
        raise ValueError("Incomplete KDD author affiliation")
    names = [" ".join(name.split()) for name in "".join(parts).split(";")]
    if not names or any(not name for name in names):
        raise ValueError("Missing KDD catalogue author")
    return names


def parse_kdd_research(text, year):
    if year not in CATALOGUES or "research track papers" not in plain(text).lower():
        raise ValueError("Unverified KDD research catalogue edition")
    parser = _CatalogueCells()
    parser.feed(text)
    parser.close()
    if parser.parts is not None or parser.table_depth:
        raise ValueError("Incomplete KDD catalogue table")
    if len(parser.cells) % 2:
        raise ValueError("KDD catalogue title/author pairs are incomplete")
    records = []
    for index in range(0, len(parser.cells), 2):
        title_cell, authors_cell = parser.cells[index:index + 2]
        match = re.fullmatch(r"(.+?)\s+DOI:\s*https://doi\.org/(10\.1145/\d+\.\d+)\s*", title_cell, re.S)
        if not match or match[2].rsplit(".", 1)[0] not in PROCEEDINGS[year]:
            raise ValueError("KDD paper has no verified main-proceedings DOI")
        title = " ".join(match[1].split())
        raw = _raw("https://doi.org/" + match[2], title, _authors(authors_cell), year, doi=match[2])
        raw.extra["inventory_scope"] = "research_track"
        records.append(raw)
    expected = len(re.findall(r"DOI:\s*https://doi\.org/", plain(text)))
    return _validate(records, expected)
