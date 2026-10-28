"""ICLR 2018-2022 official programmes with verifiable OpenReview identities.

The virtual-site JSON for 2019-2021 omits OpenReview forum identifiers. Each
year therefore uses the official artefact that retains one: the 2018/2019
schedule cards, the 2020 poster catalogue joined to PaperCopilot's OpenReview
IDs by title/abstract, and the 2021/2022 JSON's own forum links. Only accepted
main-conference posters are returned; no PDF is fetched.
"""
import html
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher

from app.cleaning import clean_author_name
from app.collectors.crossref import metadata_text
from app.collectors.publisher_toc import _raw, _validate, plain
from app.collectors.title_corrections import correct_catalogue_title

EXPECTED_POSTERS = {2018: 336, 2019: 501, 2020: 687, 2021: 860, 2022: 1095}
EXPECTED_2019_ORALS = 24
PAPERCOPILOT_2020 = (
    "https://raw.githubusercontent.com/papercopilot/paperlists/main/iclr/iclr2020.json"
)
ACCEPTED_STATUSES = {"Poster", "Spotlight", "Talk", "Oral"}
FORUM = re.compile(r"https://openreview\.net/forum\?id=([A-Za-z0-9_-]+)")


def _norm(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip().casefold()


def _clean_authors(values):
    authors, seen = [], set()
    for value in values:
        name = clean_author_name((value or "").strip())
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            authors.append(name)
    return authors


def _forum_ids(block):
    return list(dict.fromkeys(FORUM.findall(block)))


def _name_tokens(value):
    return {word for word in re.findall(r"[a-z]{3,}", (value or "").casefold())}


def _schedule_cards(text):
    return re.findall(
        r'<div class="showDetailBtn"[^>]*>(.*?)(?=<div class="showDetailBtn"|$)',
        text,
        re.S,
    )


def parse_iclr_schedule(poster_html, year, oral_html=None, *, allow_missing_authors=False):
    """Official 2018/2019 schedule cards with one OpenReview forum each.

    2019 has 19 cards whose visible titles were corrupted by a later event
    template; their verified titles come from sourced corrections. Nine 2018
    cards have an empty author footer; the caller may defer author validation
    and repair those from the official event detail pages.
    """
    if year not in (2018, 2019):
        raise ValueError("ICLR schedule parser only supports 2018-2019")
    records = []
    for block in _schedule_cards(poster_html):
        if '<div class="maincard narrower poster"' not in block:
            raise ValueError(f"Unexpected ICLR {year} schedule card")
        kind = re.search(r"maincardType'>([^<]+)</div>", block)
        title = re.search(r'<div class="maincardBody">(.*?)</div>', block, re.S)
        authors = re.search(r'<div class="maincardFooter">(.*?)</div>', block, re.S)
        event = re.search(r'id="maincard_(\d+)"', block)
        forums = _forum_ids(block)
        if kind is None or title is None or authors is None or len(forums) != 1:
            raise ValueError(f"ICLR {year} schedule card lacks a verified paper identity")
        raw = _raw(
            "https://openreview.net/forum?id=" + forums[0],
            plain(title[1]),
            [plain(value) for value in authors[1].split("&middot;")],
            year,
        )
        raw.extra["event_id"] = int(event[1]) if event else None
        raw.extra["catalogue_title"] = plain(title[1])
        before = raw.title
        correct_catalogue_title(raw)
        if kind[1].strip() not in ("Poster", "Oral") and raw.title == before:
            raise ValueError(f"ICLR {year} non-paper schedule event has no verified title")
        raw.authors = _clean_authors(raw.authors)
        records.append(raw)
    _validate(records, EXPECTED_POSTERS[year], require_authors=not allow_missing_authors)
    if year == 2019:
        if oral_html is None:
            raise ValueError("ICLR 2019 oral programme is required")
        poster_ids = {raw.extra["publisher_key"] for raw in records}
        oral_ids = set()
        for block in _schedule_cards(oral_html):
            forums = _forum_ids(block)
            if len(forums) > 1:
                raise ValueError("ICLR 2019 oral card has multiple forum links")
            if forums:
                oral_ids.add("https://openreview.net/forum?id=" + forums[0])
        if len(oral_ids) != EXPECTED_2019_ORALS or not oral_ids <= poster_ids:
            raise ValueError("ICLR 2019 oral programme is not covered by the poster catalogue")
    return records


def parse_iclr_event_authors(text, forum_id, catalogue_title):
    """2018 event detail page: one card with the same forum and title, plus speakers."""
    if '<div class="maincard narrower poster"' not in text:
        raise ValueError("ICLR 2018 event page has no poster card")
    if _forum_ids(text) != [forum_id]:
        raise ValueError("ICLR 2018 event page forum identity does not match the poster card")
    title = re.search(r'<div class="maincardBody">(.*?)</div>', text, re.S)
    if title is None or _norm(plain(title[1])) != _norm(catalogue_title):
        raise ValueError("ICLR 2018 event page title does not match the poster card")
    authors = [
        plain(value) for value in
        re.findall(r'<button id="speaker-\d+"[^>]*>(.*?)</button>', text, re.S)
    ]
    authors = _clean_authors(authors)
    if not authors:
        raise ValueError("ICLR 2018 event page has no speaker record")
    return authors


def parse_iclr2018(poster_html, year, *, allow_missing_authors=False):
    return parse_iclr_schedule(poster_html, year, allow_missing_authors=allow_missing_authors)


def parse_iclr2019(poster_html, oral_html, year):
    return parse_iclr_schedule(poster_html, year, oral_html)


def parse_iclr2020(official_text, papercopilot_text, year):
    """Official 2020 posters joined to PaperCopilot OpenReview identifiers."""
    if year != 2020:
        raise ValueError("ICLR 2020 parser only supports 2020")
    data = json.loads(official_text)
    rows = data.get("results")
    if not isinstance(rows, list) or data.get("count") != len(rows) or data.get("next"):
        raise ValueError("Incomplete ICLR 2020 conference catalogue")
    posters = [row for row in rows if row.get("eventtype") == "Poster"]
    if len(posters) != EXPECTED_POSTERS[2020] or len({row["id"] for row in posters}) != len(posters):
        raise ValueError("ICLR 2020 poster catalogue is incomplete or duplicated")
    mirror = json.loads(papercopilot_text)
    if not isinstance(mirror, list):
        raise ValueError("Invalid PaperCopilot ICLR 2020 inventory")
    accepted = [
        row for row in mirror
        if row.get("track") == "main"
        and row.get("status") in ACCEPTED_STATUSES
        and isinstance(row.get("id"), str)
        and re.fullmatch(r"[A-Za-z0-9_-]+", row["id"])
    ]
    if len(accepted) != EXPECTED_POSTERS[2020] or len({row["id"] for row in accepted}) != len(accepted):
        raise ValueError("PaperCopilot ICLR 2020 accepted inventory is incomplete or duplicated")

    by_title = defaultdict(list)
    for row in accepted:
        by_title[_norm(row.get("title"))].append(row)
    matched, used = {}, set()
    unmatched = []
    for row in posters:
        candidates = [item for item in by_title.get(_norm(row.get("name")), []) if item["id"] not in used]
        if len(candidates) == 1:
            matched[row["id"]] = candidates[0]
            used.add(candidates[0]["id"])
        elif not candidates:
            unmatched.append(row)
        else:
            raise ValueError("Ambiguous ICLR 2020 title match in PaperCopilot inventory")

    candidates = []
    for row in unmatched:
        official_tokens = _name_tokens(" ".join(a.get("fullname", "") for a in row.get("authors", [])))
        for item in accepted:
            if item["id"] in used:
                continue
            if not official_tokens & _name_tokens(item.get("author")):
                continue
            title_score = SequenceMatcher(None, _norm(row.get("name")), _norm(item.get("title"))).ratio()
            abstract_score = SequenceMatcher(None, _norm(row.get("abstract")), _norm(item.get("abstract"))).ratio()
            score = max(title_score, abstract_score)
            if score >= 0.8:
                candidates.append((score, row, item))
    candidates.sort(key=lambda entry: (-entry[0], entry[1]["id"], entry[2]["id"]))
    for _, row, item in candidates:
        if row["id"] in matched or item["id"] in used:
            continue
        matched[row["id"]] = item
        used.add(item["id"])
    if len(matched) != len(posters) or len(used) != len(accepted):
        raise ValueError("ICLR 2020 official posters and OpenReview identifiers do not align")

    records = []
    for row in posters:
        item = matched[row["id"]]
        same_title = _norm(row.get("name")) == _norm(item.get("title"))
        title = row["name"] if same_title else item["title"]
        raw = _raw(
            "https://openreview.net/forum?id=" + item["id"],
            metadata_text(title),
            [author.get("fullname") for author in row.get("authors", [])],
            year,
            abstract=row.get("abstract"),
        )
        if not same_title:
            raw.extra["publisher_title_correction"] = "PaperCopilot/OpenReview final title"
            raw.extra["catalogue_title"] = metadata_text(row.get("name") or "")
        raw.authors = _clean_authors(raw.authors)
        records.append(raw)
    return _validate(records, EXPECTED_POSTERS[2020])


def parse_iclr_links(text, year):
    """2021/2022 official posters whose JSON carries OpenReview forum links."""
    if year not in (2021, 2022):
        raise ValueError("ICLR link parser only supports 2021-2022")
    data = json.loads(text)
    rows = data.get("results")
    if not isinstance(rows, list) or data.get("count") != len(rows) or data.get("next"):
        raise ValueError(f"Incomplete ICLR {year} conference catalogue")
    posters = [row for row in rows if row.get("eventtype") == "Poster"]
    if len(posters) != EXPECTED_POSTERS[year] or len({row["id"] for row in posters}) != len(posters):
        raise ValueError(f"ICLR {year} poster catalogue is incomplete or duplicated")
    records = []
    for row in posters:
        links = []
        candidates = [row.get("paper_pdf_url")]
        candidates.extend(
            media.get("uri") for media in row.get("eventmedia") or []
            if (media.get("name") or "").casefold() == "openreview"
        )
        for candidate in candidates:
            match = FORUM.fullmatch(candidate or "")
            if match:
                links.append(match.group(1))
        links = list(dict.fromkeys(links))
        if len(links) != 1:
            raise ValueError(f"ICLR {year} poster has no unique OpenReview forum identity")
        raw = _raw(
            "https://openreview.net/forum?id=" + links[0],
            metadata_text(row.get("name") or ""),
            [author.get("fullname") for author in row.get("authors", [])],
            year,
            abstract=row.get("abstract"),
        )
        raw.authors = _clean_authors(raw.authors)
        records.append(raw)
    return _validate(records, EXPECTED_POSTERS[year])


async def fetch_iclr_inventory(read, year):
    """Return a complete 2018-2022 ICLR inventory, or None for other years."""
    if year == 2018:
        poster = await read("https://iclr.cc/Conferences/2018/Schedule?type=Poster")
        records = parse_iclr2018(poster, year, allow_missing_authors=True)
        for raw in records:
            if raw.authors:
                continue
            if raw.extra.get("event_id") is None:
                raise ValueError("ICLR 2018 poster without authors has no event identity")
            detail = await read(
                f"https://iclr.cc/Conferences/2018/Schedule?showEvent={raw.extra['event_id']}"
            )
            raw.authors = parse_iclr_event_authors(
                detail,
                raw.extra["publisher_key"].rsplit("=", 1)[-1],
                raw.extra["catalogue_title"],
            )
        return _validate(records, EXPECTED_POSTERS[year])
    if year == 2019:
        poster = await read("https://iclr.cc/Conferences/2019/Schedule?type=Poster")
        oral = await read("https://iclr.cc/Conferences/2019/Schedule?type=Oral")
        return parse_iclr2019(poster, oral, year)
    if year == 2020:
        official = await read(f"https://iclr.cc/static/virtual/data/iclr-{year}-orals-posters.json")
        mirror = await read(PAPERCOPILOT_2020)
        return parse_iclr2020(official, mirror, year)
    if year in (2021, 2022):
        return parse_iclr_links(
            await read(f"https://iclr.cc/static/virtual/data/iclr-{year}-orals-posters.json"),
            year,
        )
    return None
