"""Fail-closed OJS inventories with complete archive pagination, metadata only."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.collectors.publisher_toc import _raw, _validate

BASES = {
    "AAAI": "https://ojs.aaai.org/index.php/AAAI/",
    "ICAPS": "https://ojs.aaai.org/index.php/ICAPS/",
    "JAIR": "https://www.jair.org/index.php/jair/",
}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self, tag=None, css=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (css is None or css in child.attrs.get("class", "").split()):
                    yield child
                yield from child.walk(tag, css)

    def text(self):
        return re.sub(r"\s+", " ", "".join(c.text() if isinstance(c, Node) else c for c in self.children)).strip()


class Tree(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _url(href, base, suffix):
    url = urljoin(base, href)
    parsed, official = urlsplit(url), urlsplit(base)
    if (parsed.scheme, parsed.netloc) != (official.scheme, official.netloc) or parsed.query or parsed.fragment:
        raise ValueError("OJS link is outside its official origin")
    if not re.fullmatch(re.escape(official.path) + suffix, parsed.path):
        raise ValueError("OJS link is outside the requested publication")
    return url


def parse_archive(text, venue):
    base = BASES[venue]
    tree = Tree(text).root
    blocks = list(tree.walk(css="obj_issue_summary")) or list(tree.walk(css="issue-summary"))
    if not blocks:
        raise ValueError("OJS archive has no issue blocks")
    issues = []
    for block in blocks:
        links = list(block.walk("a", "title"))
        if len(links) != 1:
            raise ValueError("OJS archive has an ambiguous issue identity")
        link = links[0]
        url = _url(link.attrs.get("href", ""), base, r"issue/view/\d+")
        title = link.text()
        headings = list(block.walk("h2"))
        match = re.search(r"\((20\d{2}|19\d{2})\)", headings[0].text()) if headings else None
        if match:
            year = int(match[1])
        elif venue == "AAAI":
            edition = re.search(r"(?:AAAI|IAAI|EAAI)-(\d{2})\b", title, re.I)
            if not edition:
                raise ValueError("OJS issue missing its conference edition year")
            year = 2000 + int(edition[1])
        elif venue == "ICAPS":
            editions = set(re.findall(r"\bICAPS\s+((?:20|19)\d{2})\b", block.text()))
            if len(editions) != 1:
                raise ValueError("OJS issue missing an unambiguous conference edition year")
            year = int(editions.pop())
        else:
            raise ValueError("OJS archive issue is missing its publication year")
        # Copyright footers can be stale (ICAPS 2025 says copyright 2024).
        # Only the issue heading / explicit edition determines publication year.
        included = True
        if venue == "AAAI":
            included = bool(re.search(rf"AAAI-{year % 100:02d}\b", title, re.I)) and not re.search(
                r"\b(?:IAAI|EAAI|Workshop|Symposium|Doctoral|Student|Demonstration|Tutorial)\b", title, re.I
            )
        issues.append({"url": url, "year": year, "title": title, "included": bool(included)})
    if len({item["url"] for item in issues}) != len(issues):
        raise ValueError("OJS archive contains duplicate issues")
    next_links = []
    for anchor in tree.walk("a"):
        if "next" in anchor.attrs.get("class", "").split() or "next" in anchor.attrs.get("rel", "").split() or re.fullmatch(r"Next\s*[»›]?", anchor.text(), re.I):
            next_links.append(_url(anchor.attrs.get("href", ""), base, r"issue/archive/\d+"))
    next_links = list(dict.fromkeys(next_links))
    if len(next_links) > 1:
        raise ValueError("Ambiguous OJS archive pagination")
    page_range = re.search(r"\b(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)\b", re.sub(r"<[^>]*>", " ", text))
    pagination = tuple(map(int, page_range.groups())) if page_range else None
    if pagination:
        first, last, total = pagination
        if last - first + 1 != len(issues) or last > total or bool(next_links) != (last < total):
            raise ValueError("Incomplete OJS archive page")
    return issues, next_links[0] if next_links else None, pagination


def parse_issue(text, venue, year):
    tree = Tree(text).root
    blocks = list(tree.walk(css="obj_article_summary")) or list(tree.walk(css="article-summary"))
    records, expected = [], 0
    for block in blocks:
        headings = list(block.walk("h3"))
        links = list(headings[0].walk("a")) if len(headings) == 1 else []
        if len(links) != 1:
            raise ValueError("OJS article has no unique title/landing page")
        link = links[0]
        title = link.text()
        url = _url(link.attrs.get("href", ""), BASES[venue], r"article/view/\d+")
        if re.fullmatch(r"(?:Front\s?matter|Back\s?matter|Preface|Editorial|Table of Contents|Contents|Masthead)(?:\s*[:–-].*)?", title, re.I):
            continue
        expected += 1
        authors = list(block.walk(css="authors"))
        if len(authors) != 1 or not authors[0].text():
            raise ValueError("OJS article is missing authors")
        records.append(_raw(url, title, authors[0].text().split(","), year))
    return _validate(records, expected)


async def fetch_ojs_inventory(read, venue, year):
    """Require all archive pages and all selected issues before accepting a year."""
    url = BASES[venue] + "issue/archive"
    visited, issues = set(), {}
    previous_end, advertised_total = 0, None
    while url:
        if url in visited or len(visited) >= 100:
            raise ValueError("OJS archive pagination loop or limit")
        visited.add(url)
        batch, next_url, pagination = parse_archive(await read(url), venue)
        if pagination:
            first, last, total = pagination
            if first != previous_end + 1 or (advertised_total is not None and total != advertised_total):
                raise ValueError("OJS archive changed or skipped a page")
            previous_end, advertised_total = last, total
        for item in batch:
            if item["url"] in issues:
                raise ValueError("OJS archive repeats an issue between pages")
            issues[item["url"]] = item
        url = next_url
    if advertised_total is not None and len(issues) != advertised_total:
        raise ValueError("OJS archive issue total does not reconcile")
    selected = [item for item in issues.values() if item["year"] == year and item["included"]]
    if not selected:
        raise ValueError("Official OJS archive has no eligible issues for requested year")
    records = []
    for issue in selected:
        records.extend(parse_issue(await read(issue["url"]), venue, year))
    return _validate(records, len(records))
