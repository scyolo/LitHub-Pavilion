"""Published USENIX technical-session metadata; never retrieve PDF/media files."""

import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

from app.collectors.publisher_toc import _raw

SLUGS = {
    "FAST": "fast",
    "USENIX Security": "usenixsecurity",
    "OSDI": "osdi",
    "NSDI": "nsdi",
    "ACM SIGOPS ATC": "atc",
    "HotOS": "hotos",
}
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class Node:
    def __init__(self, tag="", attrs=None):
        self.tag, self.attrs, self.children = tag, attrs or {}, []

    def text(self, exclude=()):
        if self.tag in exclude:
            return ";" if self.tag == "em" else ""
        return "".join(
            c if isinstance(c, str) else c.text(exclude) for c in self.children
        )

    def find(self, predicate):
        result = [self] if predicate(self) else []
        for child in self.children:
            if isinstance(child, Node):
                result.extend(child.find(predicate))
        return result

    def has_class(self, value):
        return value in self.attrs.get("class", "").split()


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def session_url(abbr, year):
    if abbr not in SLUGS or not 2023 <= year <= 2026:
        raise ValueError("Unsupported USENIX catalog edition")
    if abbr == "ACM SIGOPS ATC" and year > 2025:
        raise ValueError(
            "USENIX ATC continuation needs a separately verified publisher"
        )
    return f"https://www.usenix.org/conference/{SLUGS[abbr]}{year % 100:02d}/technical-sessions"


def parse_sessions(text, abbr, year):
    url = session_url(abbr, year)
    tree = Tree()
    tree.feed(text)
    canonical = tree.root.find(
        lambda n: n.tag == "link" and n.attrs.get("rel") == "canonical"
    )
    headings = tree.root.find(lambda n: n.attrs.get("id") == "page-title")
    if not headings or not any("Technical Sessions" in n.text() for n in headings):
        raise ValueError("Not a USENIX technical-session inventory")
    if canonical and any(
        urljoin(url, n.attrs.get("href", "")).rstrip("/") != url for n in canonical
    ):
        raise ValueError("USENIX edition canonical URL mismatch")
    slug = url.split("/")[-2]
    prefix = f"/conference/{slug}/presentation/"
    records, seen = [], set()
    nodes = tree.root.find(lambda n: n.tag == "article" and n.has_class("node-paper"))
    for node in nodes:
        authors = node.find(lambda n: n.has_class("field-name-field-paper-people-text"))
        pdf = node.find(
            lambda n: n.has_class("usenix-schedule-media") and n.has_class("pdf")
        )
        if not pdf:
            continue
        title = node.find(lambda n: n.tag == "h2")
        links = title[0].find(lambda n: n.tag == "a") if title else []
        if len(links) != 1 or len(authors) != 1:
            raise ValueError("Published paper missing unambiguous title/authors")
        href = links[0].attrs.get("href", "")
        # This exact nonstandard page was linked in the official schedule and
        # independently returned its matching paper title (2026-10-01).
        legacy = (abbr == 'USENIX Security' and year == 2026
                  and href == '/conference/usenixsecurity26/yu-jerry')
        if not legacy and not re.fullmatch(re.escape(prefix) + r"[\w-]+", unquote(href)):
            raise ValueError("Unexpected edition or non-HTML presentation link")
        official = "https://www.usenix.org" + href
        if official in seen:
            raise ValueError("Duplicate USENIX paper identity")
        names = [
            re.sub(r"\s+", " ", a).strip(" ,;")
            for a in re.split(r";|,|\band\b", authors[0].text(exclude=("em",)))
        ]
        names = [name for name in names if name]
        if not names:
            raise ValueError("Missing USENIX paper authors")
        abstract = node.find(
            lambda n: n.has_class("field-name-field-paper-description-long")
        )
        row = _raw(
            official,
            links[0].text(),
            names,
            year,
            abstract=re.sub(r"\s+", " ", abstract[0].text()).strip()
            if abstract
            else None,
        )
        if not row.title:
            raise ValueError("Missing USENIX paper title")
        records.append(row)
        seen.add(official)
    if not records:
        raise ValueError("No published USENIX papers verified in this page")
    return records, {
        "source": url,
        "session_entries": len(nodes),
        "published_papers": len(records),
        "non_paper_entries": len(nodes) - len(records),
        "full_coverage_verified": False,
    }
