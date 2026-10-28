import asyncio
import json

import pytest

from app.collectors import iclr


def _card(kind, title, authors, forum, event=None):
    marker = f' id="maincard_{event}"' if event else ""
    return (
        '<div class="showDetailBtn"><div class="maincard narrower poster"'
        f'{marker}></div>'
        f"<div class='pull-right maincardHeader maincardType'>{kind}</div>"
        f'<div class="maincardBody">{title}</div>'
        f'<div class="maincardFooter">{" &middot; ".join(authors)}</div>'
        f'<a href="https://openreview.net/forum?id={forum}">OpenReview</a></div>'
    )


def _detail(title, forum, authors):
    buttons = "".join(
        f'<button id="speaker-{index}" class="btn"><span class="fa-solid fa-user"></span>'
        f" {author} </button>"
        for index, author in enumerate(authors)
    )
    return (
        '<div class="maincard narrower poster" id="maincard_4">'
        f'<div class="maincardBody">{title}</div>'
        f'<a href="https://openreview.net/forum?id={forum}">OpenReview</a>'
        f"{buttons}</div>"
    )


def _catalogue(rows):
    return json.dumps({"count": len(rows), "results": rows})


def _poster(name, authors, pdf=None, media=None, abstract=None, poster_id=None):
    return {
        "id": poster_id or name.lower().replace(" ", "-"),
        "eventtype": "Poster",
        "name": name,
        "authors": [{"fullname": author} for author in authors],
        "abstract": abstract,
        "paper_pdf_url": pdf,
        "eventmedia": media or [],
    }


def test_iclr2018_schedule_cards(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2018: 2})
    poster = _card("Poster", "First Paper", ["Lovelace, Ada"], "aaa") + _card(
        "Poster", "Second Paper", ["Turing, Alan"], "bbb"
    )
    records = iclr.parse_iclr2018(poster, 2018)
    assert [record.extra["publisher_key"] for record in records] == [
        "https://openreview.net/forum?id=aaa",
        "https://openreview.net/forum?id=bbb",
    ]


def test_iclr2018_empty_author_footer_uses_official_event_page(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2018: 1})
    poster = _card("Poster", "First Paper", [], "aaa", event=4)
    records = iclr.parse_iclr2018(poster, 2018, allow_missing_authors=True)
    assert records[0].authors == []
    assert records[0].extra["event_id"] == 4
    with pytest.raises(ValueError, match="missing titles/authors"):
        iclr.parse_iclr2018(poster, 2018)

    detail = _detail("First Paper", "aaa", ["Lovelace, Ada", "Turing, Alan"])
    assert iclr.parse_iclr_event_authors(detail, "aaa", "First Paper") == [
        "Lovelace, Ada",
        "Turing, Alan",
    ]
    with pytest.raises(ValueError, match="forum identity"):
        iclr.parse_iclr_event_authors(detail, "bbb", "First Paper")
    with pytest.raises(ValueError, match="title does not match"):
        iclr.parse_iclr_event_authors(detail, "aaa", "Other Paper")
    with pytest.raises(ValueError, match="no speaker record"):
        iclr.parse_iclr_event_authors(_detail("First Paper", "aaa", []), "aaa", "First Paper")


def test_iclr2018_fetch_repairs_missing_authors(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2018: 1})
    poster = _card("Poster", "First Paper", [], "aaa", event=4)
    detail = _detail("First Paper", "aaa", ["Lovelace, Ada", "Turing, Alan"])

    async def read(url):
        if url.endswith("type=Poster"):
            return poster
        if url.endswith("showEvent=4"):
            return detail
        raise AssertionError(url)

    records = asyncio.run(iclr.fetch_iclr_inventory(read, 2018))
    assert records[0].authors == ["Lovelace, Ada", "Turing, Alan"]
    assert records[0].extra["publisher_key"] == "https://openreview.net/forum?id=aaa"


def test_iclr2019_schedule_cards_require_forum_identity(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2019: 2})
    monkeypatch.setattr(iclr, "EXPECTED_2019_ORALS", 1)
    poster = _card("Poster", "First Paper", ["Lovelace, Ada"], "aaa") + _card(
        "Poster", "Second Paper", ["Turing, Alan"], "bbb"
    )
    oral = _card("Oral", "First Paper", ["Lovelace, Ada"], "aaa")
    records = iclr.parse_iclr2019(poster, oral, 2019)
    assert [record.extra["publisher_key"] for record in records] == [
        "https://openreview.net/forum?id=aaa",
        "https://openreview.net/forum?id=bbb",
    ]
    assert records[0].authors == ["Lovelace, Ada"]
    with pytest.raises(ValueError, match="verified paper identity"):
        iclr.parse_iclr2019(poster + _card("Poster", "Third", ["Hopper, Grace"], "ccc")
                            .replace('<a href="https://openreview.net/forum?id=ccc">OpenReview</a>', ""), oral, 2019)
    with pytest.raises(ValueError, match="oral programme"):
        iclr.parse_iclr2019(poster, _card("Oral", "Other", ["Hopper, Grace"], "zzz"), 2019)


def test_iclr2019_nonpaper_cards_need_sourced_correction(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2019: 1})
    monkeypatch.setattr(iclr, "EXPECTED_2019_ORALS", 1)
    card = _card(
        "Poster session #2",
        "Poster session #2",
        ["Balle, Jona", "Johnston, Nick", "Minnen, David"],
        "S1zz2i0cY7",
    )
    records = iclr.parse_iclr2019(card, _card("Oral", "x", ["Balle, Jona"], "S1zz2i0cY7"), 2019)
    assert records[0].title == "Integer Networks for Data Compression with Latent-Variable Models"
    assert records[0].extra["catalogue_title"] == "Poster session #2"
    with pytest.raises(ValueError, match="no verified title"):
        iclr.parse_iclr2019(
            _card("Coffee Break", "Coffee Break", ["Lovelace, Ada"], "nnn"),
            _card("Oral", "x", ["Lovelace, Ada"], "nnn"),
            2019,
        )


def test_iclr2020_joins_papercopilot_identifiers(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2020: 2})
    official = _catalogue([
        _poster("Exact Title", ["Ada Lovelace"], abstract="Verifiable abstract.", poster_id="one"),
        _poster("Catalogue Variant", ["Alan Turing"], abstract="A shared abstract about matching.", poster_id="two"),
    ])
    mirror = json.dumps([
        {"id": "AbC123", "track": "main", "status": "Poster", "title": "Exact Title",
         "author": "Ada Lovelace", "abstract": "Verifiable abstract."},
        {"id": "XyZ789", "track": "main", "status": "Poster", "title": "Final Revised Title",
         "author": "Alan Turing", "abstract": "A shared abstract about matching."},
        {"id": "WrK000", "track": "workshop", "status": "Poster", "title": "Workshop Paper",
         "author": "Someone Else", "abstract": "Not main conference."},
    ])
    records = iclr.parse_iclr2020(official, mirror, 2020)
    assert records[0].title == "Exact Title"
    assert records[0].extra["publisher_key"] == "https://openreview.net/forum?id=AbC123"
    assert records[1].title == "Final Revised Title"
    assert records[1].extra["catalogue_title"] == "Catalogue Variant"
    with pytest.raises(ValueError, match="accepted inventory"):
        iclr.parse_iclr2020(official, mirror.replace('"main"', '"workshop"'), 2020)


def test_iclr_links_require_unique_forum_identity(monkeypatch):
    monkeypatch.setattr(iclr, "EXPECTED_POSTERS", {2021: 2})
    body = _catalogue([
        _poster("Linked Paper", ["Ada Lovelace", "Ada Lovelace"],
                pdf="https://openreview.net/forum?id=Forum_1"),
        _poster("Media Paper", ["Alan Turing"],
                media=[{"name": "OpenReview", "uri": "https://openreview.net/forum?id=Forum_2"}]),
    ])
    records = iclr.parse_iclr_links(body, 2021)
    assert [record.extra["publisher_key"] for record in records] == [
        "https://openreview.net/forum?id=Forum_1",
        "https://openreview.net/forum?id=Forum_2",
    ]
    assert records[0].authors == ["Lovelace, Ada"]
    with pytest.raises(ValueError, match="unique OpenReview"):
        iclr.parse_iclr_links(
            _catalogue([_poster("Missing", ["Ada Lovelace"]), _poster("Also Missing", ["Alan Turing"])]),
            2021,
        )
