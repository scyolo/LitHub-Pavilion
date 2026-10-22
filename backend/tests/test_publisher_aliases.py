from dataclasses import replace

import pytest

from app.collectors.dblp import RawPaper
from app.collectors.publisher_toc import parse_pmlr
from app.models import Paper, PaperDirection
from app.services.publisher_import import apply_records

PMLR = "https://proceedings.mlr.press/v306/test26a.html"
REVIEW = "https://openreview.net/forum?id=Verified2026"


def pmlr(link=REVIEW):
    return f'''<h1>International Conference on Machine Learning</h1>
    <div class="paper"><p class="title">Verified machine learning</p>
    <span class="authors">Ada Lovelace</span>
    <a href="{PMLR}">abs</a><a href="{link}">OpenReview</a></div>'''


def test_pmlr_keeps_explicit_openreview_identity_from_the_same_paper():
    (raw,) = parse_pmlr(pmlr(), 2026, "https://proceedings.mlr.press/v306/", "ICML")
    assert raw.extra["publisher_aliases"] == [REVIEW]


@pytest.mark.parametrize(
    "link",
    [
        "https://openreview.net.evil.example/forum?id=x",
        "https://user@openreview.net/forum?id=x",
        "https://openreview.net/forum?id=x&extra=y",
    ],
)
def test_pmlr_does_not_promote_unverified_url_shapes_to_publication_aliases(link):
    (raw,) = parse_pmlr(pmlr(link), 2026, "https://proceedings.mlr.press/v306/", "ICML")
    assert not raw.extra.get("publisher_aliases")


def test_pmlr_transition_retains_id_and_manual_data_without_duplicate(
    db, sample_venue, sample_direction
):
    sample_venue.abbr = "ICML"
    original = RawPaper(
        source="manual",
        venue_key=REVIEW,
        title="Verified machine learning",
        year=2026,
        authors=["Lovelace, Ada"],
        official_url=REVIEW,
        extra={"publisher_key": REVIEW, "provenance": "publisher_toc"},
    )
    apply_records(db, [original], sample_venue)
    paper = db.query(Paper).one()
    pid = paper.id
    paper.note += "\nMy annotation"
    db.add(
        PaperDirection(
            paper_id=pid, direction_id=sample_direction.id, score=42, source="manual"
        )
    )
    db.commit()
    (raw,) = parse_pmlr(pmlr(), 2026, "https://proceedings.mlr.press/v306/", "ICML")
    first = apply_records(db, [raw], sample_venue)
    second = apply_records(db, [raw], sample_venue)
    assert first["counts"].get("new", 0) == second["counts"].get("new", 0) == 0
    assert db.query(Paper).count() == 1
    paper = db.get(Paper, pid)
    assert paper.publisher_key == REVIEW
    assert paper.official_url == PMLR
    from app.api.serializers import paper_links

    assert paper_links(paper)["official_url"] == PMLR
    assert "My annotation" in paper.note
    assert db.query(PaperDirection).one().score == 42
    assert apply_records(db, [original], sample_venue)["counts"].get("new", 0) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("authors", ["Turing, Alan"]),
        ("year", 2025),
        ("title", "A different publication"),
    ],
)
def test_explicit_alias_still_requires_same_title_authors_and_year(
    db, sample_venue, field, value
):
    sample_venue.abbr = "ICML"
    original = RawPaper(
        source="manual",
        venue_key=REVIEW,
        title="Verified machine learning",
        year=2026,
        authors=["Lovelace, Ada"],
        official_url=REVIEW,
        extra={"publisher_key": REVIEW, "provenance": "publisher_toc"},
    )
    apply_records(db, [original], sample_venue)
    (raw,) = parse_pmlr(pmlr(), 2026, "https://proceedings.mlr.press/v306/", "ICML")
    result = apply_records(db, [replace(raw, **{field: value})], sample_venue)
    assert result["counts"].get("identity_conflicts") == 1
    assert db.query(Paper).count() == 1
    assert db.query(Paper).one().publisher_key == REVIEW
