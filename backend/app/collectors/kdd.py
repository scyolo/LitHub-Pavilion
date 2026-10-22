"""KDD's published research-track catalogue: explicit article DOIs, no PDFs.

Edition URLs and proceeding identities are deliberately pinned to observed
official catalogues. Do not guess a URL or reuse last year's parsing for a new
edition; workshops/applied-data-science pages are not this inventory.
"""
import json
import re
from html.parser import HTMLParser

from app.collectors.crossref import metadata_text
from app.collectors.publisher_toc import _raw, _validate, plain

CATALOGUES = {
    2025: "https://www.kdd.org/kdd2025/research-track-papers-2/",
    2026: "https://kdd2026.kdd.org/papers/",
}
PROCEEDINGS = {2025: {"10.1145/3690624", "10.1145/3711896"},
               2026: {"10.1145/3770854", "10.1145/3770855"}}


def _parse_2026(text):
    if "kdd 2026" not in plain(text).lower():
        raise ValueError("Missing official KDD 2026 page identity")
    cycles = {}
    for match in re.finditer(r"const\s+(cycle[12]Papers)\s*=\s*\[", text):
        name = match[1]
        if name in cycles:
            raise ValueError("Duplicate KDD submission-cycle data")
        rows, end = json.JSONDecoder().raw_decode(text[match.end()-1:])
        suffix = text[match.end()-1+end:].lstrip()
        # The observed site adds a UI-only numeric id. Parse the JSON literal,
        # recognize that exact suffix, and never execute website JavaScript.
        adds_display_id = re.match(r"\.map\(\(paper,\s*index\)\s*=>\s*\(\{\s*\.\.\.paper,\s*id:\s*index\s*\}\)\);", suffix)
        if not isinstance(rows, list) or not (suffix.startswith(";") or adds_display_id):
            raise ValueError("Malformed KDD paper data")
        cycles[name] = rows
    if set(cycles) != {"cycle1Papers", "cycle2Papers"}:
        raise ValueError("Both KDD archival cycles are required")
    tracks = {'rtp':'research_track','ads':'applied_data_science_track',
              'dtb':'datasets_and_benchmarks_track','ais':'ai_for_sciences_track','bsi':'blue_sky_ideas_track'}
    papers = {}
    for name in ('cycle1Papers','cycle2Papers'):
        parent = '3770854' if name == 'cycle1Papers' else '3770855'
        for row in cycles[name]:
            doi = re.fullmatch(r'https://doi\.org/(10\.1145/' + parent + r'\.[0-9]+)', row.get('url') or '')
            if not doi or row.get('track') not in tracks or not row.get('title'):
                raise ValueError("Unverified KDD main-track paper or DOI parent")
            paper = _raw('https://doi.org/'+doi[1], metadata_text(row['title']), _authors(row.get('authors') or ''), 2026, doi=doi[1])
            paper.extra['inventory_scope'] = tracks[row['track']]
            previous = papers.get(paper.venue_key)
            if previous:
                if (previous.title != paper.title or previous.authors != paper.authors
                        or previous.extra['inventory_scope'] != paper.extra['inventory_scope']):
                    raise ValueError("Conflicting repeated KDD publication identity")
                previous.extra['catalogue_repeat_count'] = previous.extra.get('catalogue_repeat_count', 1) + 1
            else:
                papers[paper.venue_key] = paper
    return _validate(list(papers.values()), len(papers))


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
    if year == 2026:
        return _parse_2026(text)
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
        match = re.fullmatch(r"(.+?)\s+DOI:\s*https://doi\.org/(10\.1145/\d+\.\d+)\s*", title_cell, re.DOTALL)
        if not match or match[2].rsplit(".", 1)[0] not in PROCEEDINGS[year]:
            raise ValueError("KDD paper has no verified main-proceedings DOI")
        title = " ".join(match[1].split())
        raw = _raw("https://doi.org/" + match[2], title, _authors(authors_cell), year, doi=match[2])
        raw.extra["inventory_scope"] = "research_track"
        records.append(raw)
    expected = len(re.findall(r"DOI:\s*https://doi\.org/", plain(text)))
    return _validate(records, expected)
